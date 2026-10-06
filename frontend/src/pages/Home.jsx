import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, coverUrl, price, track } from "../api.js";
import { Row } from "../components/GameCard.jsx";
import { Glitch } from "../components/ui.jsx";

const GENRES = ["Action", "RPG", "Strategy", "Simulation", "Adventure", "Indie", "Racing", "Sports"];
const TICKER = [
  "32,132 GAMES INDEXED",
  "5,094,082 LIBRARY ROWS",
  "60,516 PLAYER PROFILES",
  "RANKER NDCG@10 0.292",
  "A/B EXPERIMENT home-recs-v1 LIVE",
  "EVENTS STREAMING VIA KAFKA",
];

function Featured({ game, variant }) {
  if (!game) return <div className="featured skeleton" />;
  return (
    <Link to={`/game/${game.game_id}`} className="featured" onClick={() => track("rec_click", game.game_id)}>
      <div className="featured-bg" style={{ backgroundImage: `url(${coverUrl(game.game_id)})` }} />
      <img src={coverUrl(game.game_id)} alt="" />
      <div className="featured-info">
        <span className="chip-mono">◢ TOP PICK FOR YOU · {variant}</span>
        <h3>{game.title}</h3>
        <span className="price big">{price(game.price)}</span>
      </div>
    </Link>
  );
}

export default function Home() {
  const [recs, setRecs] = useState(null);
  const [trending, setTrending] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/recommendations?k=11").then(setRecs).catch((e) => setError(e.message));
    // live "trending now" from the Kafka consumer; falls back to all-time most owned
    api("/games/trending?k=10")
      .then((t) => (t.games.length >= 5 ? setTrending({ ...t, live: true }) : api("/games?size=10").then((g) => setTrending({ games: g }))))
      .catch(() => setTrending({ games: [] }));
  }, []);

  const personal = recs?.model === "mf+ranker";

  return (
    <>
      <section className="hero">
        <div className="synth" aria-hidden="true">
          <div className="sun" />
          <div className="horizon-grid" />
        </div>
        <div className="hero-text">
          <span className="chip-mono">// NIGHT CITY GAME EXCHANGE</span>
          <h1>
            Find your next <Glitch text="OBSESSION" className="neon-pink" />
          </h1>
          <p className="muted">
            32,000 games. Recommendations learned from 60,000 real Steam libraries, ranked for you in milliseconds.
          </p>
          <div className="chips">
            {GENRES.map((g) => (
              <Link key={g} to={`/browse?genre=${g}`} className="chip">
                {g}
              </Link>
            ))}
          </div>
        </div>
        <Featured game={recs?.games?.[0]} variant={personal ? "PERSONAL MODEL" : "POPULAR"} />
      </section>

      <div className="ticker" aria-hidden="true">
        <div className="ticker-track">
          {[...TICKER, ...TICKER].map((t, i) => (
            <span key={i}>
              <b>▲</b> {t}
            </span>
          ))}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      <Row
        title="Picked for you"
        subtitle={recs ? `${personal ? "MF + XGBOOST RANKER" : "POPULARITY BASELINE"} · ARM: ${recs.variant.toUpperCase()}` : "LOADING MODEL"}
        games={recs?.games?.slice(1)}
        source="rec"
        ranked
        loading={!recs && !error}
      />
      <Row
        title="Trending on Respawn"
        subtitle={trending?.live ? "LIVE · LAST 24H" : "MOST OWNED"}
        games={trending?.games}
        loading={!trending}
      />
    </>
  );
}
