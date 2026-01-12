
const fs = require('fs');
const css = `
/* Re-adding missing styles and animations */
.btn-danger {
  padding: 0.5rem 1rem;
  border-radius: var(--radius);
  border: none;
  background: #ef4444;
  color: white;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1.25;
}
.btn-danger:hover:not(:disabled) {
  background: #dc2626;
  box-shadow: 0 1px 2px rgba(220, 38, 38, 0.3);
}
.btn-danger:active:not(:disabled) {
  transform: translateY(1px);
}
.btn-danger:disabled {
  background: #fca5a5;
  cursor: not-allowed;
  opacity: 0.7;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.4rem;
  height: 1.4rem;
  padding: 0 0.35rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  background: #e0e7ff;
  color: #3730a3;
  margin-right: 0.5rem;
}

/* Page Transitions */
@keyframes slideInFromRight {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
@keyframes slideOutToRight {
  from { transform: translateX(0); opacity: 1; }
  to { transform: translateX(100%); opacity: 0; }
}
@keyframes slideInFromLeft {
  from { transform: translateX(-100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
@keyframes slideOutToLeft {
  from { transform: translateX(0); opacity: 1; }
  to { transform: translateX(-100%); opacity: 0; }
}

.page-enter-right { animation: slideInFromRight 0.3s ease-out forwards; }
.page-exit-right { animation: slideOutToRight 0.3s ease-in forwards; }
.page-enter-left { animation: slideInFromLeft 0.3s ease-out forwards; }
.page-exit-left { animation: slideOutToLeft 0.3s ease-in forwards; }

.transitioning {
  overflow-x: hidden;
}
`;

fs.appendFileSync('src/App.css', css);
console.log('Appended CSS');
