import { createContext, useContext, useEffect, useState } from "react";
import { track } from "./api.js";

const CartContext = createContext(null);

// The cart lives in the browser. Prices shown here are a preview; the server
// prices the order at checkout and its total is what gets charged.
export function CartProvider({ children }) {
  const [items, setItems] = useState(() => JSON.parse(localStorage.getItem("respawn_cart") || "[]"));
  useEffect(() => localStorage.setItem("respawn_cart", JSON.stringify(items)), [items]);

  const add = (game) =>
    setItems((cur) => {
      if (cur.some((g) => g.game_id === game.game_id)) return cur;
      track("add_to_cart", game.game_id);
      return [...cur, game];
    });
  const remove = (id) => setItems((cur) => cur.filter((g) => g.game_id !== id));
  const clear = () => setItems([]);

  return <CartContext.Provider value={{ items, add, remove, clear }}>{children}</CartContext.Provider>;
}

export const useCart = () => useContext(CartContext);
