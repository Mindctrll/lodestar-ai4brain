import type { Persona } from '../api/types'
import type { GlyphName } from './icons'

/** The four coaches (docs/plan/09, personas), with a line in each one's voice. */
export const PERSONAS: {
  id: Persona
  name: string
  style: string
  sample: string
  icon: GlyphName
  soft: string
  strong: string
}[] = [
  {
    id: 'willow',
    icon: 'leaf',
    soft: '#dcfce7',
    strong: '#15803d',
    name: 'Willow',
    style: 'A calm mentor',
    sample: 'Steady work today. One step at a time.',
  },
  {
    id: 'spark',
    icon: 'zap',
    soft: '#fef3c7',
    strong: '#a16207',
    name: 'Spark',
    style: 'An energetic trainer',
    sample: 'Faster than last time! Ready for the next one?',
  },
  {
    id: 'sage',
    icon: 'book',
    soft: '#e0f2fe',
    strong: '#0069a8',
    name: 'Sage',
    style: 'A factual analyst',
    sample: 'Estimate up, range narrower. That is the update.',
  },
  {
    id: 'buddy',
    name: 'Buddy',
    style: 'A casual friend',
    sample: 'Nice one. Another?',
    icon: 'thumb',
    soft: '#fce7f3',
    strong: '#be185d',
  },
]
