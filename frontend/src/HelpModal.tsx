import React from 'react';

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const HelpModal: React.FC<HelpModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  const segmentationExamples = {
    as_is: {
      title: "原文模式",
      description: "整篇不切分，导入1条待标注对象",
      example: `在某航空结构件的制造过程中，加工任务由机加车间负责实施。操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对，确认该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。在正式加工前，张伟对所使用的立式加工中心进行了点检，确保设备状态满足精加工要求。

在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。该工序使用 Φ16 硬质合金立铣刀，切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。加工过程中，操作人员需持续观察切削状态，并根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。

完成粗加工后，零件进入半精加工与精加工工序。精加工工艺名称为“数控铣削精加工”，重点保证关键尺寸和表面质量。操作人员李强依据 GB/T 1804—2000《一般公差》对加工精度进行控制，并使用游标卡尺和高度尺进行尺寸检测。最终，经检验确认零件尺寸合格，表面粗糙度满足 Ra 1.6 μm 的设计要求，零件转入下一道装配工序。`,
      result: "✅ 1个标注对象：整篇文章作为一个整体进行标注",
      useCases: ["短文本标注", "完整文档分析", "整体情感分析"]
    },
    paragraph: {
      title: "段落模式", 
      description: "按空行分段，每段作为1条待标注对象",
      example: `段落 1
在某航空结构件的制造过程中，加工任务由机加车间负责实施。操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对，确认该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。在正式加工前，张伟对所使用的立式加工中心进行了点检，确保设备状态满足精加工要求。

段落 2
在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。该工序使用 Φ16 硬质合金立铣刀，切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。加工过程中，操作人员需持续观察切削状态，并根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。

段落 3
完成粗加工后，零件进入半精加工与精加工工序。精加工工艺名称为“数控铣削精加工”，重点保证关键尺寸和表面质量。操作人员李强依据 GB/T 1804—2000《一般公差》对加工精度进行控制，并使用游标卡尺和高度尺进行尺寸检测。最终，经检验确认零件尺寸合格，表面粗糙度满足 Ra 1.6 μm 的设计要求，零件转入下一道装配工序。`,
      result: "✅ 3个标注对象：\n1. 第一段：在某航空结构件...精加工要求。\n2. 第二段：在粗加工阶段...异常磨损。\n3. 第三段：完成粗加工后...装配工序。",
      useCases: ["段落主题提取", "分段情感分析", "内容结构化"]
    },
    sentence: {
      title: "句子模式",
      description: "按句末标点切分，每句作为1条待标注对象", 
      example: `在某航空结构件的制造过程中，加工任务由机加车间负责实施。
操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对。
该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。
在正式加工前，张伟对所使用的立式加工中心进行了点检。
设备状态经确认后满足精加工要求。
在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。
该工序使用 Φ16 硬质合金立铣刀。
切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。
加工过程中，操作人员需持续观察切削状态。
根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。
...（后续句子）`,
      result: "✅ 多个标注对象：\n1. 在某航空结构件的制造过程中...\n2. 操作人员张伟依据工艺规程文件...\n3. 该零件材料为 7075-T6 铝合金...\n...",
      useCases: ["句子级实体识别", "语法分析", "句子分类"]
    }
  };

  const stats = [
    { number: "1", label: "原文模式：适合短文本" },
    { number: "3-10", label: "段落模式：适合中等长度文本" },
    { number: "10+", label: "句子模式：适合详细分析" }
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content-large" onClick={e => e.stopPropagation()}>
        <div className="modal-header-large">
          <h2 className="modal-title-large">🎯 切分方式详细说明</h2>
          <button className="modal-close-btn" onClick={onClose}>×</button>
        </div>
        
        <div className="modal-body-large">
          <div className="help-section">
            <h3>📋 切分方式对比</h3>
            
            {Object.entries(segmentationExamples).map(([key, data]) => (
              <div key={key} className="help-method">
                <div className="method-header">
                  <div className="method-icon">
                    {key === 'as_is' && '📄'}
                    {key === 'paragraph' && '📝'}
                    {key === 'sentence' && '💬'}
                  </div>
                  <div>
                    <div className="method-title">{data.title}</div>
                    <div className="method-description">{data.description}</div>
                  </div>
                </div>
                
                <div className="example-section">
                  <div className="example-title">📝 输入示例：</div>
                  <div className="example-content">{data.example}</div>
                  
                  <div className="example-title">✨ 切分结果：</div>
                  <div className="example-result">{data.result}</div>
                  
                  <div className="example-title">🎯 适用场景：</div>
                  <div style={{ marginTop: '0.5rem' }}>
                    {data.useCases.map((useCase, index) => (
                      <span key={index} style={{
                        display: 'inline-block',
                        background: '#e0e7ff',
                        color: '#4338ca',
                        padding: '0.25rem 0.75rem',
                        borderRadius: '9999px',
                        fontSize: '0.75rem',
                        marginRight: '0.5rem',
                        marginBottom: '0.5rem'
                      }}>
                        {useCase}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="help-section">
            <h3>📊 使用建议</h3>
            <div className="usage-stats">
              {stats.map((stat, index) => (
                <div key={index} className="stat-item">
                  <span className="stat-number">{stat.number}</span>
                  <div className="stat-label">{stat.label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="tips-section">
            <div className="tips-title">💡 使用技巧</div>
            <ul className="tips-list">
              <li>根据文本长度选择合适的切分方式，避免产生过多或过少的标注对象</li>
              <li>原文模式适合短文本，段落模式适合结构化文档，句子模式适合详细分析</li>
              <li>切分后的每个对象都会独立保存，可以分别进行标注和修改</li>
              <li>选择切分方式后，系统会自动预览切分结果，确认无误后再导入</li>
              <li>不同切分方式会影响标注效率，建议根据具体任务需求选择</li>
            </ul>
          </div>

          <div style={{ 
            marginTop: '2rem', 
            padding: '1.5rem', 
            background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%)',
            border: '1px solid #0ea5e9',
            borderRadius: '0.75rem'
          }}>
            <div style={{ 
              fontSize: '1rem', 
              fontWeight: '600', 
              color: '#0c4a6e',
              marginBottom: '0.75rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}>
              🚀 快速开始
            </div>
            <div style={{ color: '#0c4a6e', lineHeight: 1.6 }}>
              1. 拖拽或选择文本文件 📁<br/>
              2. 选择合适的切分方式 🎯<br/>
              3. 预览切分结果 👀<br/>
              4. 开始标注工作 ✏️<br/>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default HelpModal;