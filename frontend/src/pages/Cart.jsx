import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, price } from "../api.js";
import { useCart } from "../cart.jsx";

export default function Cart() {
  const { items, remove, clear } = useCart();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
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
      setStatus({ ok: true, text: `Order #${res.order_id} confirmed: $${res.total.toFixed(2)} charged. Games added to your library.` });
      clear();
    } catch (e) {
      setStatus({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="cart">
      <h1>Your cart</h1>
      {status && <p className={status.ok ? "success" : "error"}>{status.text}</p>}
      {!items.length && !status && (
        <p className="muted">
          Empty. <Link to="/browse">Go find something.</Link>
        </p>
      )}
      {items.map((g) => (
        <div key={g.game_id} className="cart-line">
          <Link to={`/game/${g.game_id}`}>{g.title}</Link>
          <span>{price(g.price)}</span>
          <button className="ghost" onClick={() => remove(g.game_id)}>Remove</button>
        </div>
      ))}
      {items.length > 0 && (
        <div className="cart-total">
          <span>Estimated total {price(total)}</span>
          <button className="primary" disabled={busy} onClick={checkout}>
            {busy ? "Processing…" : "Checkout"}
          </button>
        </div>
      )}
    </section>
  );
}
