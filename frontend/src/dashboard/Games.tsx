import { useState } from 'react'

import type { Registry } from '../api/types'
import { Glyph } from '../app/icons'
import { GAMES } from '../games'
import { FAMILIES } from './families'

type Game = Registry['games'][number]

const minutes = (s: number) => (s < 90 ? '1 min' : `${String(Math.round(s / 60))} min`)

/** The games library (docs/plan/06): every game the browser can run, grouped by the family of
 * its main skill, plus the Detective story and a game made to order. Playing one goes to the
 * conversation, as if the user had asked for it. */
export function Games({ registry, onPlay }: { registry: Registry; onPlay: (ask: string) => void }) {
  const [family, setFamily] = useState<string | null>(null)
  const dim = (id: string) => registry.dimensions.find((d) => d.id === id)
  const familyOf = (g: Game) => {
    const main = Object.entries(g.dims).sort((a, b) => b[1] - a[1])[0]?.[0]
    return (main && dim(main)?.group) ?? 'style'
  }
  const games = registry.games.filter(
    (g) => g.kind === 'game' && g.available && g.id !== 'custom_blocks' && g.id in GAMES,
  )
  const families = Object.keys(FAMILIES).filter((f) => games.some((g) => familyOf(g) === f))
  const shown = family ? games.filter((g) => familyOf(g) === family) : games
  const story = registry.games.find((g) => g.kind === 'story' && g.story)

  return (
    <div className="stack" data-testid="games">
      <div className="games__feature">
        {story?.story && (
          <section className="story-card">
            <p className="story-card__eyebrow">Story mode</p>
            <h2>{story.name}</h2>
            <p className="story-card__intro">{story.story.intro}</p>
            <ol className="story-card__chapters">
              {story.story.chapters.map((c) => (
                <li key={c.game}>
                  <strong>{c.title}</strong>
                  <span>{registry.games.find((g) => g.id === c.game)?.name ?? c.game}</span>
                </li>
              ))}
            </ol>
            <button
              type="button"
              className="story-card__go"
              onClick={() => {
                onPlay('play the Detective story')
              }}
            >
              Start the case
            </button>
          </section>
        )}
        <section className="maker-card">
          <span className="maker-card__icon">
            <Glyph name="spark" />
          </span>
          <h2>Make a game</h2>
          <p>Describe a game and Lodestar builds it from tested pieces, scored like the others.</p>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onPlay('Make me a game')
            }}
          >
            Make me a game
          </button>
        </section>
      </div>

      <section className="games__library">
        <div className="games__head">
          <h2>
            {games.length} games <span className="muted">to play right now</span>
          </h2>
          <div className="games__filters" role="group" aria-label="Skill family">
            <button
              type="button"
              className="chip chip--small"
              aria-pressed={family === null}
              onClick={() => {
                setFamily(null)
              }}
            >
              All
            </button>
            {families.map((f) => (
              <button
                key={f}
                type="button"
                className="chip chip--small"
                aria-pressed={family === f}
                onClick={() => {
                  setFamily(f)
                }}
              >
                {FAMILIES[f]?.label ?? f}
              </button>
            ))}
          </div>
        </div>
        <ul className="games__grid">
          {shown.map((g) => {
            const colour = FAMILIES[familyOf(g)] ?? { soft: '#f1f5f9', strong: '#314158' }
            const skills = Object.entries(g.dims)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 2)
              .map(([d]) => dim(d)?.name ?? d)
            return (
              <li key={g.id} className="game-card">
                <div className="game-card__top">
                  <span
                    className="game-card__badge"
                    style={{ background: colour.soft, color: colour.strong }}
                  >
                    {g.name.slice(0, 1)}
                  </span>
                  <span className="muted small">{minutes(g.duration_s)}</span>
                </div>
                <h3>{g.name}</h3>
                <p className="game-card__does">{GAMES[g.id]?.instructions ?? g.does}</p>
                <p className="game-card__skills">{skills.join(' · ')}</p>
                <button
                  type="button"
                  className="small"
                  onClick={() => {
                    onPlay(`play ${g.name}`)
                  }}
                >
                  Play
                </button>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}
