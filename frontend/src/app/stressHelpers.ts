import type { PatternsView, WhyLine } from '../api/types'
import type { SkillMark } from '../dashboard/NightSky'

/** The lines of evidence stored on a decision ("why|source|text"). */
export function evidenceLines(evidence: string[] | undefined): WhyLine[] {
  return (evidence ?? []).flatMap((e) => {
    if (!e.startsWith('why|')) return []
    const [, source = '', ...text] = e.split('|')
    return [{ source, text: text.join('|') }]
  })
}

export function skillMarks(patterns: PatternsView | null): Record<string, SkillMark> {
  const marks: Record<string, SkillMark> = {}
  for (const p of patterns?.plateaus ?? []) marks[p.dim] = 'plateau'
  // A skill on a track shows its track: that's what decides its next game.
  if (patterns?.split) {
    marks[patterns.split.advanced.dim] = 'advanced'
    marks[patterns.split.foundation.dim] = 'foundation'
  }
  return marks
}
