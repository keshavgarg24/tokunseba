"use client";

import { useState } from "react";

/** One command, with a button that puts it on the clipboard and says so. */
export function Copy({ cmd }: { cmd: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="copyline">
      <span className="dim" style={{ color: "#7FB0FF" }}>$</span>
      <span>{cmd}</span>
      <button
        data-done={done ? "1" : "0"}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(cmd);
            setDone(true);
            setTimeout(() => setDone(false), 1600);
          } catch {
            // A browser that refuses the clipboard is not an error worth showing. The
            // command is right there to select.
          }
        }}
      >
        {done ? "copied" : "copy"}
      </button>
    </div>
  );
}
