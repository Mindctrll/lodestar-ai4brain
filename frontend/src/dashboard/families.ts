/** Each family of skills has a colour, used on the Brain Twin map and the games library. */
export const FAMILIES: Record<string, { label: string; soft: string; strong: string }> = {
  attention: { label: 'Attention', soft: '#e0f2fe', strong: '#0069a8' },
  control: { label: 'Self-control', soft: '#ede9fe', strong: '#6d28d9' },
  memory: { label: 'Memory', soft: '#fce7f3', strong: '#be185d' },
  reasoning: { label: 'Reasoning', soft: '#dcfce7', strong: '#15803d' },
  language: { label: 'Words and numbers', soft: '#ffedd5', strong: '#c2410c' },
  speed: { label: 'Speed and timing', soft: '#fef3c7', strong: '#a16207' },
  style: { label: 'Thinking style', soft: '#f1f5f9', strong: '#314158' },
}
