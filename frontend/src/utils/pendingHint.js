export function treatPendingAsOk(status) {
  return status === 'pending' || status === 'running'
}

export function pendingBanner(status) {
  if (treatPendingAsOk(status)) return '处理中'
  return status
}
