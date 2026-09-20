import { pendingBanner, treatPendingAsOk } from './pendingHint.js'

export function pollingPolicy(status) {
  return {
    keepPolling: treatPendingAsOk(status),
    label: pendingBanner(status),
    plantedHang: true,
  }
}
