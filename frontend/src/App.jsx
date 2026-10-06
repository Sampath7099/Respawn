import { useEffect } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { currentUser, logout, track } from "./api.js";
import { useCart } from "./cart.jsx";
import { Logo } from "./components/ui.jsx";
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

  useEffect(() => {
    track("page_view");
    window.scrollTo(0, 0);
  }, [location.pathname]);

  if (location.pathname === "/login") return <Login />;

  return (
    <>
      <header className="nav">
        <Link to="/" aria-label="Respawn home">
          <Logo />
        </Link>
        <nav>
          <NavLink to="/" end>Store</NavLink>
          <NavLink to="/browse">Browse</NavLink>
          <NavLink to="/library">Library</NavLink>
          <NavLink to="/admin">Analytics</NavLink>
        </nav>
        <div className="nav-right">
          <Link to="/cart" className={`cart-btn ${items.length ? "has-items" : ""}`}>
            CART <b key={items.length}>{items.length}</b>
          </Link>
          <span className="user" title={user}>
            <i className="dot" /> {user}
          </span>
          <button className="ghost small" onClick={logout}>
            Jack out
          </button>
        </div>
      </header>
      <main key={location.pathname} className="page">
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
      <footer>
        <span className="mono">// RESPAWN v1</span> · UCSD Steam dataset · shoppers are real Steam libraries, traffic is
        simulated
      </footer>
    </>
  );
}
