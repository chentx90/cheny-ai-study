export function formatScore(score: number): string {
  return (score * 100).toFixed(1) + '%'
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}