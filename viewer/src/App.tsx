import { useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { EmptyState } from "./components";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";
import { ShowDetail } from "./pages/ShowDetail";

export function App() {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");

  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="brand">
          peblo tv
        </NavLink>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Home
          </NavLink>
          <NavLink to="/search" className={({ isActive }) => (isActive ? "active" : "")}>
            Browse
          </NavLink>
        </nav>
        <form
          className="searchbox"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(`/search?q=${encodeURIComponent(term)}`);
          }}
        >
          <input
            type="search"
            placeholder="Search shows and episodes"
            aria-label="Search shows and episodes"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
        </form>
      </header>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/shows/:slug" element={<ShowDetail />} />
        <Route
          path="*"
          element={<EmptyState title="There's nothing here." hint="Try the home screen." />}
        />
      </Routes>
    </>
  );
}
