import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

/** 左侧品牌插画 —— 扁平城市/数据平台场景 */
function BrandIllustration() {
  return (
    <svg viewBox="0 0 340 280" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* 天空渐变 */}
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#DBEAFE" stopOpacity=".5" />
          <stop offset="100%" stopColor="#EFF6FF" stopOpacity=".1" />
        </linearGradient>
        <linearGradient id="b1" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#93C5FD" />
          <stop offset="100%" stopColor="#BFDBFE" />
        </linearGradient>
        <linearGradient id="b2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#60A5FA" />
          <stop offset="100%" stopColor="#93C5FD" />
        </linearGradient>
        <linearGradient id="b3" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3B82F6" />
          <stop offset="100%" stopColor="#60A5FA" />
        </linearGradient>
      </defs>

      {/* 背景天空 */}
      <rect width="340" height="280" fill="url(#sky)" />

      {/* 远山 */}
      <path d="M0 220 Q60 170 120 200 Q160 185 200 210 Q250 180 300 195 Q320 190 340 200 L340 280 L0 280Z" fill="#DBEAFE" opacity=".4" />

      {/* 地面 */}
      <rect x="0" y="225" width="340" height="55" fill="#E2E8F0" opacity=".5" />

      {/* 建筑群 —— 左侧 */}
      <rect x="25" y="150" width="28" height="75" rx="3" fill="url(#b1)" opacity=".7" />
      <rect x="32" y="140" width="7" height="10" rx="1" fill="#BFDBFE" />
      <rect x="32" y="155" width="7" height="3" fill="#fff" opacity=".5" />
      <rect x="32" y="162" width="7" height="3" fill="#fff" opacity=".5" />
      <rect x="32" y="169" width="7" height="3" fill="#fff" opacity=".5" />
      <rect x="32" y="176" width="7" height="3" fill="#fff" opacity=".3" />

      <rect x="60" y="135" width="32" height="90" rx="4" fill="url(#b2)" opacity=".7" />
      <rect x="68" y="125" width="7" height="10" rx="1" fill="#93C5FD" />
      <rect x="68" y="140" width="7" height="4" fill="#fff" opacity=".5" />
      <rect x="68" y="149" width="7" height="4" fill="#fff" opacity=".5" />
      <rect x="68" y="158" width="7" height="4" fill="#fff" opacity=".5" />
      <rect x="68" y="167" width="7" height="4" fill="#fff" opacity=".5" />
      <rect x="68" y="176" width="7" height="4" fill="#fff" opacity=".4" />
      <rect x="68" y="185" width="7" height="4" fill="#fff" opacity=".3" />

      {/* 建筑群 —— 中间主楼 */}
      <rect x="100" y="110" width="38" height="115" rx="4" fill="url(#b3)" opacity=".8" />
      <rect x="110" y="90" width="8" height="20" rx="2" fill="#60A5FA" />
      {/* 窗户 */}
      {[100,112,124,136,148,160,172,184,196].map((y, i) => (
        <rect key={`mw${i}`} x="108" y={y} width="10" height="5" rx="1" fill="#fff" opacity={i % 3 === 0 ? .5 : i % 3 === 1 ? .4 : .3} />
      ))}
      {[100,112,124,136,148,160,172,184,196].map((y, i) => (
        <rect key={`mw2${i}`} x="123" y={y} width="10" height="5" rx="1" fill="#fff" opacity={i % 3 === 0 ? .4 : i % 3 === 1 ? .3 : .5} />
      ))}

      {/* 建筑群 —— 右侧 */}
      <rect x="148" y="145" width="30" height="80" rx="3" fill="url(#b1)" opacity=".65" />
      <rect x="156" y="130" width="7" height="15" rx="1" fill="#BFDBFE" />
      <rect x="156" y="150" width="7" height="3" fill="#fff" opacity=".5" />
      <rect x="156" y="157" width="7" height="3" fill="#fff" opacity=".5" />
      <rect x="156" y="164" width="7" height="3" fill="#fff" opacity=".4" />

      <rect x="186" y="155" width="25" height="70" rx="3" fill="url(#b2)" opacity=".6" />
      <rect x="193" y="145" width="6" height="10" rx="1" fill="#93C5FD" />
      <rect x="193" y="160" width="6" height="3" fill="#fff" opacity=".4" />
      <rect x="193" y="167" width="6" height="3" fill="#fff" opacity=".4" />

      {/* 数据节点/连接线 */}
      <circle cx="119" cy="82" r="5" fill="#3B82F6" opacity=".3" />
      <circle cx="119" cy="82" r="2.5" fill="#3B82F6" opacity=".6" />
      <line x1="119" y1="87" x2="119" y2="110" stroke="#3B82F6" strokeWidth="1" opacity=".2" strokeDasharray="3 3" />

      <circle cx="170" cy="70" r="4" fill="#60A5FA" opacity=".25" />
      <circle cx="170" cy="70" r="2" fill="#60A5FA" opacity=".5" />

      <circle cx="80" cy="115" r="3.5" fill="#93C5FD" opacity=".3" />
      <circle cx="80" cy="115" r="1.8" fill="#93C5FD" opacity=".5" />

      {/* 前景云 */}
      <ellipse cx="280" cy="55" rx="35" ry="12" fill="#fff" opacity=".4" />
      <ellipse cx="265" cy="50" rx="20" ry="10" fill="#fff" opacity=".35" />
      <ellipse cx="40" cy="40" rx="25" ry="9" fill="#fff" opacity=".3" />
    </svg>
  )
}

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('请填写账号和密码')
      return
    }
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate('/app')
    } catch (err: any) {
      setError(err.message || '登录失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        {/* ===== 左侧品牌面板 ===== */}
        <div className="login-brand">
          <div>
            <div className="login-brand-top">
              <div className="login-brand-logo">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
              </div>
              <span className="login-brand-name">LabelFast</span>
            </div>
            <p className="login-brand-tagline">
              高效、精准的数据标注平台<br />助力 AI 训练数据生产
            </p>
          </div>
          <div className="login-brand-illustration">
            <BrandIllustration />
          </div>
        </div>

        {/* ===== 右侧表单面板 ===== */}
        <div className="login-form-panel">
          <div className="login-form-wrapper">
            <h1 className="login-form-title">欢迎登录</h1>
            <p className="login-form-desc">请登录进入标注平台</p>

            {/* 账号提示 */}
            <div className="login-notice">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 1 }}>
                <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
              <span>账号由管理员在 <code>backend/users.xlsx</code> 中统一维护</span>
            </div>

            {/* 错误提示 */}
            {error && (
              <div className="login-error">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit}>
              {/* 账号 */}
              <div className="login-field">
                <div className="login-input-wrap">
                  <input
                    className="login-input"
                    type="text"
                    placeholder="邮箱 / 手机号 / 用户名"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    autoFocus
                  />
                </div>
              </div>

              {/* 密码 */}
              <div className="login-field">
                <div className="login-input-wrap">
                  <input
                    className="login-input"
                    type={showPwd ? 'text' : 'password'}
                    placeholder="请输入密码"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="login-input-icon"
                    onClick={() => setShowPwd(!showPwd)}
                    tabIndex={-1}
                    aria-label={showPwd ? '隐藏密码' : '显示密码'}
                  >
                    {showPwd ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                        <line x1="1" y1="1" x2="23" y2="23" />
                      </svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              {/* 辅助行 */}
              <div className="login-actions-row">
                <label className="login-remember">
                  <input type="checkbox" />
                  记住我
                </label>
                <a className="login-forgot" href="#forgot">忘记密码？</a>
              </div>

              {/* 按钮 */}
              <div className="login-btn-row">
                <button className="login-btn login-btn-primary" type="submit" disabled={submitting}>
                  {submitting ? (
                    <>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" style={{ animation: 'spin .8s linear infinite' }}>
                        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                      </svg>
                      验证中...
                    </>
                  ) : '登 录'}
                </button>
                <button className="login-btn login-btn-outline" type="button" title="注册（由管理员操作）" tabIndex={-1}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="19" y1="8" x2="19" y2="14" /><line x1="22" y1="11" x2="16" y2="11" />
                  </svg>
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* ===== 底部链接 ===== */}
        <div className="login-footer">
          <a href="#privacy">隐私政策</a>
          <a href="#terms">用户协议</a>
          <a href="#help">帮助中心</a>
          <span>© 2026 LabelFast</span>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
