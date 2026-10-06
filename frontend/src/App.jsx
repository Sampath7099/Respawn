import { useEffect } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { currentUser, logout, track } from "./api.js";
import { useCart } from "./cart.jsx";
import Admin from "./pages/Admin.jsx";
import Browse from "./pages/Browse.jsx";
import Cart from "./pages/Cart.jsx";
import Game from "./pages/Game.jsx";
import Home from "./pages/Home.jsx";
import Library from "./pages/Library.jsx";
import Login from "./pages/Login.jsx";

function Protected({ children }) {
  return currentUser() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const location = useLocation();
  const { items } = useCart();
  const user = currentUser();

  useEffect(() => track("page_view"), [location.pathname]);

  if (location.pathname === "/login") return <Login />;

  return (
    <>
      <header className="nav">
        <Link to="/" className="logo">
          RE<span>SPAWN</span>
        </Link>
        <nav>
          <NavLink to="/" end>Store</NavLink>
          <NavLink to="/browse">Browse</NavLink>
          <NavLink to="/library">Library</NavLink>
          <NavLink to="/admin">Analytics</NavLink>
        </nav>
        <div className="nav-right">
          <Link to="/cart" className="cart-btn">
            Cart <b>{items.length}</b>
          </Link>
          <span className="user">{user}</span>
          <button
            className="ghost"
            onClick={logout}
          >
            Log out
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Protected><Home /></Protected>} />
          <Route path="/browse" element={<Protected><Browse /></Protected>} />
          <Route path="/game/:id" element={<Protected><Game /></Protected>} />
          <Route path="/cart" element={<Protected><Cart /></Protected>} />
          <Route path="/library" element={<Protected><Library /></Protected>} />
          <Route path="/admin" element={<Protected><Admin /></Protected>} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
      <footer>Built on the UCSD Steam dataset · shoppers are real Steam libraries, traffic is simulated</footer>
    </>
  );
}
