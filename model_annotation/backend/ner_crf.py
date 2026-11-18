"""
CRF (Conditional Random Field) layer for sequence labeling.

Implements a linear-chain CRF with:
- Negative log-likelihood loss (forward algorithm for log Z)
- Viterbi decoding for optimal tag sequence inference
"""

import torch
import torch.nn as nn


class CRF(nn.Module):
    """Linear-chain Conditional Random Field.

    Tag 0 serves dual purpose as both START and END boundary marker:
    - ``transitions[0, :]`` — starting transition scores: score to begin a
      sequence with each tag (tag 0 -> tag j).
    - ``transitions[:, 0]`` — ending transition scores: score to end a
      sequence from each tag (tag i -> tag 0).
    These boundary transitions are used in the forward algorithm for log-Z
    computation, in gold-score calculation, and in Viterbi decoding.

    Parameters
    ----------
    num_tags : int
        Number of output tags (e.g., BIOES labels). Must be >= 2.
    batch_first : bool, default=True
        Whether the input tensors have batch as first dimension.
        When True, emissions shape is (batch, seq_len, num_tags).
    """

    def __init__(self, num_tags: int, batch_first: bool = True):
        super().__init__()
        if num_tags < 2:
            raise ValueError("num_tags must be at least 2")
        self.num_tags = num_tags
        self.batch_first = batch_first

        # Transition matrix: transitions[i][j] = score for i -> j
        # Tag 0 serves as an implicit START tag (and END tag).
        # transitions[0][j] = score to start with tag j
        # transitions[i][0] = score to end with tag i
        self.transitions = nn.Parameter(torch.randn(num_tags, num_tags) / 10)

    def forward(
        self,
        emissions: torch.Tensor,
        tags: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        """Compute negative log-likelihood (NLL) loss.

        loss = -(gold_score - log_Z) = log_Z - gold_score

        Parameters
        ----------
        emissions : Tensor (batch, seq_len, num_tags)
            Emission scores from the encoder (e.g., BERT + linear projection).
        tags : LongTensor (batch, seq_len)
            Ground-truth tag indices, padded with any value where mask == False.
        mask : BoolTensor (batch, seq_len)
            True for valid tokens, False for padding.

        Returns
        -------
        loss : scalar Tensor
            Scalar NLL loss averaged over the batch.
        """
        if not self.batch_first:
            emissions = emissions.transpose(0, 1)
            tags = tags.transpose(0, 1)
            mask = mask.transpose(0, 1)

        batch_size = emissions.size(0)
        gold_score = self._compute_score(emissions, tags, mask)
        forward_score = self._forward_alpha(emissions, mask)

        # NLL averaged over batch
        loss = (forward_score - gold_score) / batch_size
        return loss

    def decode(
        self,
        emissions: torch.Tensor,
        mask: torch.Tensor,
    ) -> list[list[int]]:
        """Viterbi decoding: find the optimal tag sequence for each sample.

        Parameters
        ----------
        emissions : Tensor (batch, seq_len, num_tags)
            Emission scores.
        mask : BoolTensor (batch, seq_len)
            True for valid tokens.

        Returns
        -------
        best_paths : list[list[int]]
            Optimal tag sequence for each sample in the batch.
        """
        if not self.batch_first:
            emissions = emissions.transpose(0, 1)
            mask = mask.transpose(0, 1)

        return self._viterbi_decode(emissions, mask)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_score(
        self,
        emissions: torch.Tensor,
        tags: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        """Compute the unnormalised score of the gold path for each sample.

        score(x, y) = sum_t emission[y_t] + sum_t transition[y_{t-1} -> y_t]

        With tag 0 as implicit START (pos 0) and END (pos T-1).
        """
        batch_size, seq_len, num_tags = emissions.shape
        device = emissions.device

        # Clamp tags to valid range for safe indexing: padding positions use -100,
        # which would cause CUDA OOB errors in gather and index_select.
        # Since the mask zeroes out padding positions later, using any valid
        # index for padding is harmless.
        safe_tags = torch.clamp(tags, min=0, max=self.num_tags - 1)

        # --- Emission scores ---
        # shape: (batch, seq_len)
        emission_scores = emissions.gather(
            dim=2, index=safe_tags.unsqueeze(-1)
        ).squeeze(-1)

        # --- Transition scores ---
        # Build the previous tag tensor: for position 0 prev_tag = 0 (START)
        prev_tags = torch.zeros(batch_size, seq_len, dtype=torch.long, device=device)
        prev_tags[:, 1:] = safe_tags[:, :-1]

        # Gather transition scores for (prev_tag -> curr_tag) at every position
        # transitions shape: (num_tags, num_tags)
        trans_scores = self.transitions[prev_tags, safe_tags]

        # --- End transition ---
        # Last valid position transitions to END (tag 0)
        seq_len_counts = mask.long().sum(dim=1)  # (batch,)
        valid_mask = (seq_len_counts > 0)  # (batch,); False for all-mask samples

        # Sum over positions, applying mask to exclude padding
        seq_score = ((emission_scores + trans_scores) * mask.float()).sum(dim=1)

        # End transition: last valid tag -> tag 0 (END).
        # For all-mask samples (seq_len == 0), the clamped last_indices are
        # meaningless; valid_mask zeroes them out so score becomes 0.
        last_indices = (seq_len_counts - 1).clamp(min=0)  # (batch,)
        last_tags = safe_tags[torch.arange(batch_size, device=device), last_indices]  # (batch,)
        end_scores = self.transitions[last_tags, torch.zeros(batch_size, dtype=torch.long, device=device)]

        total_score = (seq_score + end_scores) * valid_mask.float()
        return total_score.sum()

    def _forward_alpha(
        self,
        emissions: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        """Compute log(Z) = log partition function using the forward algorithm.

        alpha[t][j] = log sum over all paths ending at position t with tag j
                     of exp(total score up to t)
        """
        batch_size, seq_len, num_tags = emissions.shape
        device = emissions.device

        # Initialise: alpha[0][j] = start_transition[0->j] + emission[0][j]
        # transitions[0, :] = start transitions
        alpha = self.transitions[0, :].unsqueeze(0) + emissions[:, 0, :]  # (batch, num_tags)

        for t in range(1, seq_len):
            # alpha: (batch, num_tags)
            # Next: logsumexp(alpha[:, k] + transitions[k, j]) + emission[:, t, j]
            # = logsumexp(alpha.unsqueeze(2) + transitions.unsqueeze(0), dim=1)
            emit_t = emissions[:, t, :]  # (batch, num_tags)

            # alpha_expanded: (batch, num_tags, 1)
            # trans_expanded: (1, num_tags, num_tags)
            # score_partial: (batch, num_tags, num_tags) — score of path ending at (t, j) via prev tag k
            score_partial = alpha.unsqueeze(2) + self.transitions.unsqueeze(0)

            alpha_next = torch.logsumexp(score_partial, dim=1) + emit_t  # (batch, num_tags)

            # Apply mask: only update valid positions
            mask_t = mask[:, t].unsqueeze(1)  # (batch, 1)
            alpha = alpha_next * mask_t + alpha * (~mask_t)

        # Termination: add end transitions (transitions[k, 0])
        # alpha shape: (batch, num_tags)
        end_trans = self.transitions[:, 0].unsqueeze(0)  # (1, num_tags)
        z = torch.logsumexp(alpha + end_trans, dim=1)  # (batch,)
        return z.sum()

    def _viterbi_decode(
        self,
        emissions: torch.Tensor,
        mask: torch.Tensor,
    ) -> list[list[int]]:
        """Viterbi algorithm for optimal tag sequence."""
        batch_size, seq_len, num_tags = emissions.shape
        device = emissions.device

        # Backpointers: (batch, seq_len, num_tags) — stores index of previous best tag
        backpointers = torch.zeros(batch_size, seq_len, num_tags, dtype=torch.long, device=device)

        # Initialise
        delta = self.transitions[0, :].unsqueeze(0) + emissions[:, 0, :]  # (batch, num_tags)

        for t in range(1, seq_len):
            # delta: (batch, num_tags) — best score ending at (t-1, k)
            # transitions: (num_tags, num_tags)
            # Compute: delta.unsqueeze(2) + transitions.unsqueeze(0) => (batch, num_tags, num_tags)
            scores = delta.unsqueeze(2) + self.transitions.unsqueeze(0)
            delta_next, best_prev = scores.max(dim=1)  # (batch, num_tags) each
            delta_next = delta_next + emissions[:, t, :]

            backpointers[:, t, :] = best_prev

            # Mask
            mask_t = mask[:, t].unsqueeze(1)
            delta = delta_next * mask_t + delta * (~mask_t)

        # Termination: add end transitions
        end_trans = self.transitions[:, 0].unsqueeze(0)  # (1, num_tags)
        delta_end = delta + end_trans
        _, best_last_tag = delta_end.max(dim=1)  # (batch,)

        # Backtrack
        best_paths: list[list[int]] = []
        for b in range(batch_size):
            seq_len_count = int(mask[b].long().sum().item())
            if seq_len_count == 0:
                best_paths.append([])
                continue
            path: list[int] = []
            prev_tag = best_last_tag[b].item()
            # Backtrack from last valid position down to position 0
            for t in range(seq_len_count - 1, 0, -1):
                path.append(prev_tag)
                prev_tag = backpointers[b, t, prev_tag].item()
            path.append(prev_tag)
            path.reverse()
            best_paths.append(path)
        return best_paths
