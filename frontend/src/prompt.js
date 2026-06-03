function normalizeText(value) {
  return String(value ?? '').trim().replace(/\s+/g, ' ')
}

function truncateText(value, maxLength = 600) {
  const text = normalizeText(value)
  if (text.length <= maxLength) {
    return text
  }
  return `${text.slice(0, maxLength)}…`
}

export function buildRagPrompt(question, sources) {
  const safeQuestion = normalizeText(question)
  const sourceBlocks = Array.isArray(sources) && sources.length > 0
    ? sources.map((source, index) => {
        const filename = source?.filename || '未知文档'
        const chunkIndex = Number.isFinite(Number(source?.chunk_index)) ? Number(source.chunk_index) : 0
        const score = Number.isFinite(Number(source?.score)) ? Number(source.score).toFixed(3) : '0.000'
        const content = truncateText(source?.content, 700) || '（空内容）'

        return [
          `【资料 ${index + 1}】`,
          `文件：${filename}`,
          `chunk：${chunkIndex}`,
          `相似度：${score}`,
          `内容：${content}`,
        ].join('\n')
      }).join('\n\n')
    : '无可用参考资料。'

  return [
    '你是公司内部知识库问答助手。请仅根据【参考资料】回答【问题】。',
    '',
    '要求：',
    '1. 如果资料足够，请直接给出简洁、准确的回答。',
    '2. 如果资料不足，请明确说明“未检索到足够资料”。',
    '3. 尽量在回答末尾用“引用来源： [1] [2] ...”标明你依据了哪些资料。',
    '4. 不要编造资料中没有的信息。',
    '',
    '【参考资料】',
    sourceBlocks,
    '',
    '【问题】',
    safeQuestion,
  ].join('\n')
}

export function extractAssistantMessage(messages) {
  if (!Array.isArray(messages)) {
    return ''
  }

  const assistantMessages = messages.filter((message) => message?.role === 'assistant')
  return String(assistantMessages.at(-1)?.content ?? '').trim()
}

