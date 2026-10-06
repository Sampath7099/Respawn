import { useState } from "react";
import { Link } from "react-router-dom";
import { coverUrl, price, track } from "../api.js";

// `source` = "rec" when the card sits in the recommendation row, so clicks
// are logged as rec_click (the A/B test's primary metric) instead of game_click.
export default function GameCard({ game, source }) {
  const [broken, setBroken] = useState(false);
  return (
    <Link
      to={`/game/${game.game_id}`}
      className="card"
      onClick={() => track(source === "rec" ? "rec_click" : "game_click", game.game_id)}
    >
      {broken ? (
        <div className="cover placeholder">{game.title}</div>
      ) : (
        <img className="cover" src={coverUrl(game.game_id)} alt={game.title} loading="lazy" onError={() => setBroken(true)} />
      )}
      <div className="card-body">
        <div className="card-title">{game.title}</div>
        <div className="card-meta">
          <span className="tag">{game.primary_genre}</span>
          <span className="price">{price(game.price)}</span>
        </div>
      </div>
    </Link>
  );
}

export function Row({ title, subtitle, games, source }) {
  if (!games?.length) return null;
  return (
    <section className="row">
      <div className="row-head">
        <h2>{title}</h2>
        {subtitle && <span className="muted">{subtitle}</span>}
      </div>
      <div className="grid">
        {games.map((g) => (
          <GameCard key={g.game_id} game={g} source={source} />
        ))}
      </div>
    </section>
  );
}
