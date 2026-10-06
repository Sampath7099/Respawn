import { createContext, useContext, useEffect, useState } from "react";
import { track } from "./api.js";

const CartContext = createContext(null);

// Cart lives in the browser (localStorage); the server only sees it at checkout.
export function CartProvider({ children }) {
  const [items, setItems] = useState(() => JSON.parse(localStorage.getItem("respawn_cart") || "[]"));
  useEffect(() => localStorage.setItem("respawn_cart", JSON.stringify(items)), [items]);

  const add = (game) => {
    if (items.some((g) => g.game_id === game.game_id)) return;
    track("add_to_cart", game.game_id);
    setItems([...items, game]);
  };
  const remove = (id) => setItems(items.filter((g) => g.game_id !== id));
  const clear = () => setItems([]);

  return <CartContext.Provider value={{ items, add, remove, clear }}>{children}</CartContext.Provider>;
}

export const useCart = () => useContext(CartContext);
