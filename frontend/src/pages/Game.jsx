import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, coverUrl, price } from "../api.js";
import { useCart } from "../cart.jsx";
import { Row } from "../components/GameCard.jsx";
import { useToast } from "../components/ui.jsx";

function Meter({ label, value, display }) {
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <b>{display}</b>
      </div>
      <div className="meter-bar">
        <i style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
      </div>
    </div>
  );
}

export default function Game() {
  const { id } = useParams();
  const [game, setGame] = useState(null);
  const [similar, setSimilar] = useState(null);
  const [wished, setWished] = useState(false);
  const cart = useCart();
  const toast = useToast();

  useEffect(() => {
    setGame(null);
    setSimilar(null);
    setWished(false);
    api(`/games/${id}`).then(setGame).catch((e) => toast(e.message, "err"));
    api(`/games/${id}/similar`).then(setSimilar).catch(() => setSimilar([]));
  }, [id, toast]);

  if (!game) {
    return (
      <div className="game-loading">
        <span className="loader" /> <span className="mono">DECRYPTING GAME DATA…</span>
      </div>
    );
  }
  const inCart = cart.items.some((g) => g.game_id === game.game_id);
  const forSale = game.price !== null && game.price !== undefined;
  const genres = (game.genres || "").split(", ").filter(Boolean);

  return (
    <>
      <div className="backdrop" style={{ backgroundImage: `url(${coverUrl(game.game_id)})` }} aria-hidden="true" />
      <Link to="/browse" className="back mono">◂ BACK TO BROWSE</Link>
      <section className="game">
        <div className="game-cover-frame">
          <img className="game-cover" src={coverUrl(game.game_id)} alt={game.title} />
        </div>
        <div className="game-info">
          <span className="chip-mono">ID #{game.game_id} · {game.price_band?.toUpperCase()}</span>
          <h1>{game.title}</h1>
          <p className="muted">
            {game.developer || "Unknown studio"} {game.release_date && `· ${game.release_date.slice(0, 4)}`}
          </p>
          <div className="chips">
            {genres.map((g) => (
              <Link key={g} to={`/browse?genre=${encodeURIComponent(g)}`} className="tag">
                {g}
              </Link>
            ))}
          </div>
          <div className="hud">
            <div><b>{Number(game.owners).toLocaleString()}</b><span>owners in dataset</span></div>
            <div><b>{Math.round(game.total_hours).toLocaleString()}</b><span>hours played</span></div>
            <div><b>{game.sentiment || "—"}</b><span>steam sentiment</span></div>
          </div>
          {game.review_count > 0 && (
            <Meter
              label={`Players recommend (${game.review_count} reviews)`}
              value={game.recommend_rate}
              display={`${Math.round(game.recommend_rate * 100)}%`}
            />
          )}
          <div className="buy">
            <span className="big-price">{price(game.price)}</span>
            <button
              className="primary"
              disabled={inCart || !forSale}
              onClick={() => {
                cart.add(game);
                toast(`${game.title} added to cart`);
              }}
            >
              {!forSale ? "Unavailable" : inCart ? "In cart ✓" : "Add to cart"}
            </button>
            <button
              className="ghost"
              disabled={wished}
              onClick={() =>
                api(`/wishlist/${game.game_id}`, { method: "POST" })
                  .then(() => {
                    setWished(true);
                    toast("Saved to wishlist");
                  })
                  .catch((e) => toast(e.message, "err"))
              }
            >
              {wished ? "♥ Wishlisted" : "♡ Wishlist"}
            </button>
          </div>
        </div>
      </section>
      <Row
        title="More like this"
        subtitle="NEAREST NEIGHBOURS · LEARNED EMBEDDINGS"
        games={similar}
        loading={similar === null}
      />
    </>
  );
}
