import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function LoginPage() {
  const { login, register } = useAuth()
  const navigate = useNavigate()

  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [fade, setFade] = useState(false)

  // 切换登录/注册模式时添加过渡动画
  const switchMode = () => {
    setFade(true)
    setError('')
    setTimeout(() => {
      setIsRegister(!isRegister)
      setFade(false)
    }, 200)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // 基本校验
    if (!username.trim() || !password.trim()) {
      setError('请填写用户名和密码')
      return
    }

    // 注册模式下检查密码确认
    if (isRegister && password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    setSubmitting(true)
    try {
      if (isRegister) {
        await register(username.trim(), password)
      } else {
        await login(username.trim(), password)
      }
      navigate('/app')
    } catch (err: any) {
      setError(err.message || '操作失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        {/* 开发环境提示 */}
        <div style={{
          background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 8,
          padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#92400e',
          textAlign: 'center', lineHeight: 1.6
        }}>
          🔧 <strong>开发环境</strong><br/>
          账号：<code style={{background:'#fde68a',padding:'1px 6px',borderRadius:3}}>admin</code>
          密码：<code style={{background:'#fde68a',padding:'1px 6px',borderRadius:3}}>admin123</code>
        </div>

        {/* 卡片头部 */}
        <div className="login-card-header">
          <div className="login-card-icon">📝</div>
          <h2 className="login-card-title">
            {isRegister ? '创建账号' : '文本标注器'}
          </h2>
          <p className="login-card-subtitle">
            {isRegister ? '加入团队开始标注' : '高效标注，精准分类'}
          </p>
        </div>

        {/* 错误提示 */}
        {error && <div className="login-error">{error}</div>}

        {/* 表单区域 */}
        <div className={`login-form-area${fade ? ' fade' : ''}`}>
          <form onSubmit={handleSubmit}>
            {/* 用户名字段 */}
            <div className="login-field">
              <div className="login-field-label">用户名</div>
              <input
                className="login-input"
                type="text"
                placeholder="请输入用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </div>

            {/* 密码字段 */}
            <div className="login-field">
              <div className="login-field-label">密码</div>
              <input
                className="login-input"
                type="password"
                placeholder="请输入密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            {/* 注册模式下显示确认密码 */}
            {isRegister && (
              <div className="login-field">
                <div className="login-field-label">确认密码</div>
                <input
                  className="login-input"
                  type="password"
                  placeholder="请再次输入密码"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                />
              </div>
            )}

            {/* 提交按钮 */}
            <button
              className="login-submit-btn"
              type="submit"
              disabled={submitting}
            >
              {submitting
                ? (isRegister ? '注册中...' : '登录中...')
                : (isRegister ? '注 册' : '登 录')}
            </button>
          </form>

          {/* 底部切换链接 */}
          <div className="login-switch">
            {isRegister ? '已有账号？' : '还没有账号？'}
            <button className="login-switch-link" type="button" onClick={switchMode}>
              {isRegister ? '去登录' : '立即注册'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
