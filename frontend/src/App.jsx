import { useState, useRef, useEffect, useCallback } from 'react'

const css = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: system-ui, -apple-system, sans-serif;
    background: #111;
    color: #eee;
    min-height: 100vh;
  }

  /* ---- Header ---- */
  .header {
    position: sticky;
    top: 0;
    z-index: 10;
    background: #1a1a1a;
    border-bottom: 1px solid #333;
    padding: 12px 16px;
  }

  .header-inner {
    max-width: 1400px;
    margin: 0 auto;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .header h1 {
    font-size: 1.1rem;
    font-weight: 600;
    color: #fff;
    margin-right: 4px;
    white-space: nowrap;
  }

  .search-input {
    flex: 1 1 260px;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid #444;
    background: #252525;
    color: #eee;
    font-size: 0.95rem;
    outline: none;
  }
  .search-input:focus { border-color: #666; }

  .date-input {
    padding: 7px 10px;
    border-radius: 6px;
    border: 1px solid #444;
    background: #252525;
    color: #eee;
    font-size: 0.85rem;
    outline: none;
  }
  .date-input:focus { border-color: #666; }

  .date-label {
    font-size: 0.8rem;
    color: #888;
    white-space: nowrap;
  }

  .search-btn {
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
    background: #4a7fcb;
    color: #fff;
    font-size: 0.95rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .search-btn:hover { background: #5a8fdb; }
  .search-btn:disabled { background: #334; cursor: default; }

  /* ---- Status bar ---- */
  .status {
    max-width: 1400px;
    margin: 10px auto 0;
    padding: 0 16px;
    font-size: 0.85rem;
    color: #888;
    min-height: 1.4em;
  }
  .status.error { color: #e07070; }

  /* ---- Grid ---- */
  .grid {
    max-width: 1400px;
    margin: 12px auto 32px;
    padding: 0 16px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }

  /* ---- Card ---- */
  .card {
    background: #1e1e1e;
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
    border: 1px solid #2a2a2a;
  }
  .card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.5);
  }

  .card-img-wrap {
    width: 100%;
    aspect-ratio: 4/3;
    overflow: hidden;
    background: #111;
  }
  .card-img-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .card-meta {
    padding: 8px 10px;
    font-size: 0.78rem;
    color: #aaa;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .card-score { color: #7cb9e8; font-weight: 600; }
  .card-filename {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #ccc;
  }

  /* ---- Lightbox ---- */
  .lightbox {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: rgba(0,0,0,0.92);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: zoom-out;
  }
  .lightbox img {
    max-width: 95vw;
    max-height: 95vh;
    object-fit: contain;
    border-radius: 4px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.8);
  }
  .lightbox-close {
    position: absolute;
    top: 16px;
    right: 20px;
    font-size: 2rem;
    color: #bbb;
    background: none;
    border: none;
    cursor: pointer;
    line-height: 1;
  }
  .lightbox-close:hover { color: #fff; }
`

function imageUrl(path) {
  return '/api/image?path=' + encodeURIComponent(path)
}

function formatDate(iso) {
  if (!iso) return ''
  return iso.slice(0, 10)
}

function Card({ photo, onClick }) {
  return (
    <div className="card" onClick={() => onClick(photo)}>
      <div className="card-img-wrap">
        <img
          src={imageUrl(photo.file_path)}
          alt={photo.file_name}
          loading="lazy"
        />
      </div>
      <div className="card-meta">
        <span className="card-score">
          {photo.similarity != null ? (photo.similarity * 100).toFixed(1) + '%' : ''}
        </span>
        {photo.date_taken && <span>{formatDate(photo.date_taken)}</span>}
        {photo.camera_model && <span>{photo.camera_model}</span>}
        <span className="card-filename">{photo.file_name}</span>
      </div>
    </div>
  )
}

function Lightbox({ photo, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="lightbox" onClick={onClose}>
      <button className="lightbox-close" onClick={onClose} aria-label="Close">×</button>
      <img
        src={imageUrl(photo.file_path)}
        alt={photo.file_name}
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
  const [after, setAfter] = useState('')
  const [before, setBefore] = useState('')
  const [results, setResults] = useState([])
  const [status, setStatus] = useState('')
  const [isError, setIsError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [lightboxPhoto, setLightboxPhoto] = useState(null)
  const abortRef = useRef(null)

  const doSearch = useCallback(async () => {
    if (!query.trim()) return

    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()

    setLoading(true)
    setIsError(false)
    setStatus('Searching…')
    setResults([])

    try {
      const body = { query: query.trim(), limit: 20 }
      if (after) body.after = after
      if (before) body.before = before

      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abortRef.current.signal,
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(`Server error ${res.status}: ${text}`)
      }

      const data = await res.json()
      setResults(data)
      setStatus(data.length === 0 ? 'No results found.' : `${data.length} result(s)`)
    } catch (err) {
      if (err.name === 'AbortError') return
      setIsError(true)
      setStatus(err.message)
    } finally {
      setLoading(false)
    }
  }, [query, after, before])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') doSearch()
  }

  return (
    <>
      <style>{css}</style>

      <header className="header">
        <div className="header-inner">
          <h1>MyPictures</h1>
          <input
            className="search-input"
            type="text"
            placeholder="Search photos…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <span className="date-label">From</span>
          <input
            className="date-input"
            type="date"
            value={after}
            onChange={(e) => setAfter(e.target.value)}
          />
          <span className="date-label">To</span>
          <input
            className="date-input"
            type="date"
            value={before}
            onChange={(e) => setBefore(e.target.value)}
          />
          <button className="search-btn" onClick={doSearch} disabled={loading}>
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>
      </header>

      <div className={`status${isError ? ' error' : ''}`}>{status}</div>

      <main className="grid">
        {results.map((photo) => (
          <Card key={photo.file_path} photo={photo} onClick={setLightboxPhoto} />
        ))}
      </main>

      {lightboxPhoto && (
        <Lightbox photo={lightboxPhoto} onClose={() => setLightboxPhoto(null)} />
      )}
    </>
  )
}
