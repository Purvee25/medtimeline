import type { Marker } from '../api/schemas'

/** Category definitions: label, icon (SVG path / emoji), and which marker codes belong. */
const CATEGORIES: { label: string; icon: string; codes: string[] }[] = [
  {
    label: 'All Tests',
    icon: '🔬',
    codes: [], // empty = show all
  },
  {
    label: 'Blood Count',
    icon: '🩸',
    codes: ['hb', 'wbc', 'rbc', 'plt'],
  },
  {
    label: 'Lipid Profile',
    icon: '🫀',
    codes: ['chol', 'hdl', 'ldl', 'tg'],
  },
  {
    label: 'Inflammation',
    icon: '🌡️',
    codes: ['crp'],
  },
]

interface MarkerTabsProps {
  markers: Marker[] | undefined
  selected: string
  onSelect: (code: string) => void
}

export function MarkerTabs({ markers, selected, onSelect }: MarkerTabsProps) {
  if (!markers) return null

  // Determine which category the selected marker belongs to (for tab highlight).
  const activeCategory: (typeof CATEGORIES)[number] =
    CATEGORIES.find((c) => c.codes.includes(selected)) ?? CATEGORIES[0]!

  // Markers visible in the chip list below the tabs.
  const visibleMarkers =
    activeCategory.codes.length === 0
      ? markers
      : markers.filter((m) => activeCategory.codes.includes(m.code))

  return (
    <div className="marker-tabs-wrap">
      {/* Category tabs */}
      <div className="marker-cat-bar" role="tablist" aria-label="Test category">
        {CATEGORIES.map((cat) => {
          const isActive = cat === activeCategory
          return (
            <button
              key={cat.label}
              role="tab"
              aria-selected={isActive}
              className={`marker-cat-tab${isActive ? ' active' : ''}`}
              onClick={() => {
                // When switching categories, jump to the first marker in that category.
                const first = cat.codes.length === 0 ? markers[0]?.code : cat.codes.find((c) => markers.some((m) => m.code === c))
                if (first) onSelect(first)
              }}
            >
              <span className="cat-icon" aria-hidden="true">{cat.icon}</span>
              <span>{cat.label}</span>
            </button>
          )
        })}
      </div>

      {/* Marker chips */}
      <div className="marker-chip-bar" role="tablist" aria-label="Select test">
        {visibleMarkers.map((m) => (
          <button
            key={m.code}
            role="tab"
            aria-selected={m.code === selected}
            className={`marker-chip${m.code === selected ? ' active' : ''}`}
            onClick={() => onSelect(m.code)}
          >
            {m.name}
          </button>
        ))}
      </div>
    </div>
  )
}
