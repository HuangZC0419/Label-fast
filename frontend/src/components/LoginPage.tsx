import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // 基本校验
    if (!username.trim() || !password.trim()) {
      setError('请填写用户名和密码')
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
        {/* 开发环境提示 */}
        <div style={{
          background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 8,
          padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#92400e',
          textAlign: 'center', lineHeight: 1.6
        }}>
          <strong>账号由管理员维护</strong><br/>
          请使用 <code style={{background:'#fde68a',padding:'1px 6px',borderRadius:3}}>backend/users.xlsx</code> 中配置的用户名和密码登录
        </div>

        {/* 卡片头部 */}
        <div className="login-card-header">
          <div className="login-card-icon">📝</div>
          <h2 className="login-card-title">文本标注器</h2>
          <p className="login-card-subtitle">高效标注，精准分类</p>
        </div>

        {/* 错误提示 */}
        {error && <div className="login-error">{error}</div>}

        {/* 表单区域 */}
        <div className="login-form-area">
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

            {/* 提交按钮 */}
            <button
              className="login-submit-btn"
              type="submit"
              disabled={submitting}
            >
              {submitting ? '登录中...' : '登 录'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
