import type { Persona } from '../api/types'

/** The four coaches (docs/plan/09, personas), with a line in each one's voice. */
export const PERSONAS: { id: Persona; name: string; style: string; sample: string }[] = [
  {
    id: 'willow',
    name: 'Willow',
    style: 'A calm mentor',
    sample: 'Steady work today. One step at a time.',
  },
  {
    id: 'spark',
    name: 'Spark',
    style: 'An energetic trainer',
    sample: 'Faster than last time! Ready for the next one?',
  },
  {
    id: 'sage',
    name: 'Sage',
    style: 'A factual analyst',
    sample: 'Estimate up, range narrower. That is the update.',
  },
  { id: 'buddy', name: 'Buddy', style: 'A casual friend', sample: 'Nice one. Another?' },
]
