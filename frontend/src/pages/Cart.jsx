import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, coverUrl, price } from "../api.js";
import { useCart } from "../cart.jsx";
import { useToast } from "../components/ui.jsx";

export default function Cart() {
  const { items, remove, clear } = useCart();
  const [receipt, setReceipt] = useState(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  // One idempotency key per cart: retrying the same cart reuses it (never charged
  // twice); changing the cart makes a new key (the server rejects a reused key for a different cart).
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    key.current = crypto.randomUUID();
  }, [items]);

  const total = items.reduce((s, g) => s + Number(g.price), 0);

  const checkout = async () => {
    setBusy(true);
    try {
      const res = await api("/checkout", {
        method: "POST",
        body: { game_ids: items.map((g) => g.game_id) },
        headers: { "Idempotency-Key": key.current },
      });
      setReceipt({ ...res, titles: items.map((g) => g.title) });
      clear();
      toast(`Order #${res.order_id} confirmed`);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  };

  if (receipt) {
    return (
      <section className="cart">
        <div className="receipt">
          <span className="chip-mono">TRANSACTION COMPLETE</span>
          <h1 className="section-title">Order #{receipt.order_id}</h1>
          {receipt.titles.map((t) => (
            <div key={t} className="receipt-line mono">
              <span>+ {t}</span>
            </div>
          ))}
          <div className="receipt-total mono">
            CHARGED <b>${receipt.total.toFixed(2)}</b>
          </div>
          <div className="buy">
            <Link to="/library" className="btn primary">Open library</Link>
            <Link to="/" className="btn ghost">Keep shopping</Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="cart">
      <div className="page-head">
        <h1 className="section-title">Your cart</h1>
        <span className="chip-mono">{items.length} ITEM{items.length === 1 ? "" : "S"}</span>
      </div>
      {!items.length && (
        <div className="empty">
          <span className="mono neon-pink">CART EMPTY</span>
          <p className="muted">
            <Link to="/browse" className="link">Go find something ▸</Link>
          </p>
        </div>
      )}
      {items.map((g) => (
        <div key={g.game_id} className="cart-line">
          <img src={coverUrl(g.game_id)} alt="" />
          <Link to={`/game/${g.game_id}`}>{g.title}</Link>
          <span className="price">{price(g.price)}</span>
          <button className="ghost small" onClick={() => remove(g.game_id)} aria-label={`Remove ${g.title}`}>
            ✕
          </button>
        </div>
      ))}
      {items.length > 0 && (
        <div className="cart-total">
          <span className="mono">
            ESTIMATED TOTAL <b>{price(total)}</b>
          </span>
          <button className="primary" disabled={busy} onClick={checkout}>
            {busy ? "Processing…" : "Checkout ▸"}
          </button>
        </div>
      )}
    </section>
  );
}
