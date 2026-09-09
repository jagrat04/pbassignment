import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Loading } from "./components";
import { EpisodeEdit } from "./pages/EpisodeEdit";
import { Login } from "./pages/Login";
import { Publish } from "./pages/Publish";
import { ShowEdit } from "./pages/ShowEdit";
import { ShowList } from "./pages/ShowList";

export function App() {
  const { user, ready, logout, canPublish } = useAuth();

  if (!ready) {
    return (
      <div className="page">
        <Loading rows={3} label="Starting up" />
      </div>
    );
  }
  if (!user) return <Login />;

  return (
    <>
      <header className="topbar">
        <span className="brand">Peblo CMS</span>
        <nav>
          <NavLink to="/shows" className={({ isActive }) => (isActive ? "active" : "")}>
            Shows
          </NavLink>
          <NavLink to="/publish" className={({ isActive }) => (isActive ? "active" : "")}>
            Publish
          </NavLink>
        </nav>
        <span className="small muted">
          {user.name} · {canPublish ? "admin" : "editor"}
        </span>
        <button onClick={logout} style={{ padding: "4px 10px", fontSize: 13 }}>
          Sign out
        </button>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/shows" replace />} />
        <Route path="/shows" element={<ShowList />} />
        <Route path="/shows/:showId" element={<ShowEdit />} />
        <Route path="/shows/:showId/episodes/:episodeId" element={<EpisodeEdit />} />
        <Route path="/publish" element={<Publish />} />
        <Route
          path="*"
          element={
            <div className="page">
              <div className="empty">
                <p>That page doesn't exist.</p>
                <NavLink to="/shows">Back to shows</NavLink>
              </div>
            </div>
          }
        />
      </Routes>
    </>
  );
}
