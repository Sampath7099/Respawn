import { createContext, useCallback, useContext, useState } from "react";

export function Logo({ big = false }) {
  return (
    <span className={`logo ${big ? "big" : ""}`}>
      RE<span>SPAWN</span>
    </span>
  );
}

// Text with a chromatic glitch: two offset copies (cyan/magenta) flicker on top via CSS.
export function Glitch({ as: Tag = "span", text, className = "" }) {
  return (
    <Tag className={`glitch ${className}`} data-text={text}>
      {text}
    </Tag>
  );
}

export function SkeletonGrid({ count = 10 }) {
  return (
    <div className="grid">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card skeleton" style={{ animationDelay: `${i * 60}ms` }}>
          <div className="cover" />
          <div className="card-body">
            <div className="line" />
            <div className="line short" />
          </div>
        </div>
      ))}
    </div>
  );
}

const ToastContext = createContext(() => {});

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((text, kind = "ok") => {
    const id = crypto.randomUUID();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span className="toast-tag">{t.kind === "ok" ? "SYS//OK" : "SYS//ERR"}</span> {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
