export const OFFLINE_MESSAGE = 'Cannot reach MarketMirror. Is it still running?'

// fetch rejects with a TypeError when the server or the network is down; a
// response error carries a useful message from the API instead.
export function isNetworkError(error) {
  return error instanceof TypeError ||
    /failed to fetch|networkerror|load failed|network request failed/i.test(String(error?.message || ''))
}

export function requestErrorText(error) {
  return isNetworkError(error) ? OFFLINE_MESSAGE : (error?.message || 'Something went wrong.')
}
