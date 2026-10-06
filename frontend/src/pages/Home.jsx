import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Row } from "../components/GameCard.jsx";

const GENRES = ["Action", "RPG", "Strategy", "Simulation", "Adventure", "Indie", "Racing", "Sports"];

export default function Home() {
  const [recs, setRecs] = useState(null);
  const [trending, setTrending] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/recommendations?k=10").then(setRecs).catch((e) => setError(e.message));
    api("/games?size=10").then(setTrending).catch(() => {});
  }, []);

  return (
    <>
      <section className="hero">
        <div>
          <h1>
            Find your next <span className="neon">obsession</span>
          </h1>
          <p className="muted">32,000 games. Recommendations learned from 5 million real Steam libraries.</p>
          <div className="chips">
            {GENRES.map((g) => (
              <Link key={g} to={`/browse?genre=${g}`} className="chip">
                {g}
              </Link>
            ))}
          </div>
        </div>
      </section>

      {error && <p className="error">{error}</p>}
      {recs && (
        <Row
          title="Picked for you"
          subtitle={`${recs.model === "mf+ranker" ? "personalised model" : "most popular"} · A/B arm: ${recs.variant}`}
          games={recs.games}
          source="rec"
        />
      )}
      <Row title="Trending on Respawn" subtitle="most owned" games={trending} />
    </>
  );
}
