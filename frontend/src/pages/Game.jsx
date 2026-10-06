import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, coverUrl, price } from "../api.js";
import { useCart } from "../cart.jsx";
import { Row } from "../components/GameCard.jsx";

export default function Game() {
  const { id } = useParams();
  const [game, setGame] = useState(null);
  const [similar, setSimilar] = useState([]);
  const [wished, setWished] = useState(false);
  const cart = useCart();

  useEffect(() => {
    setGame(null);
    setWished(false);
    api(`/games/${id}`).then(setGame);
    api(`/games/${id}/similar`).then(setSimilar).catch(() => setSimilar([]));
    window.scrollTo(0, 0);
  }, [id]);

  if (!game) return <p className="muted">Loading…</p>;
  const inCart = cart.items.some((g) => g.game_id === game.game_id);
  const forSale = game.price !== null && game.price !== undefined;

  return (
    <>
      <section className="game">
        <img className="game-cover" src={coverUrl(game.game_id)} alt={game.title} />
        <div className="game-info">
          <h1>{game.title}</h1>
          <p className="muted">
            {game.developer} {game.release_date && `· ${game.release_date.slice(0, 4)}`}
          </p>
          <div className="chips">
            {(game.genres || "").split(", ").filter(Boolean).map((g) => (
              <span key={g} className="tag">{g}</span>
            ))}
          </div>
          <div className="stats">
            <div><b>{Number(game.owners).toLocaleString()}</b><span>owners in dataset</span></div>
            <div><b>{Math.round(game.total_hours).toLocaleString()}</b><span>hours played</span></div>
            <div><b>{game.sentiment || "—"}</b><span>reviews</span></div>
          </div>
          <div className="buy">
            <span className="big-price">{price(game.price)}</span>
            <button className="primary" disabled={inCart || !forSale} onClick={() => cart.add(game)}>
              {!forSale ? "Unavailable" : inCart ? "In cart" : "Add to cart"}
            </button>
            <button
              className="ghost"
              disabled={wished}
              onClick={() => api(`/wishlist/${game.game_id}`, { method: "POST" }).then(() => setWished(true))}
            >
              {wished ? "♥ Wishlisted" : "♡ Wishlist"}
            </button>
          </div>
        </div>
      </section>
      <Row title="More like this" subtitle="nearest games in the learned embedding space" games={similar} />
    </>
  );
}
