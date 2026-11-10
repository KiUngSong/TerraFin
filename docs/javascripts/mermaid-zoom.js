// Zoom, drag-to-pan and full screen for Mermaid diagrams.
// Material draws each diagram in a closed shadow root, so this scales the host
// element (div.mermaid) instead of the SVG inside it.
(() => {
  const STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4];
  const ACTUAL = STEPS.indexOf(1);
  // Outside full screen a zoomed diagram scrolls inside this share of the window height.
  const MAX_VIEW_HEIGHT = 0.8;

  const button = (text, label, onClick) => {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = text;
    element.title = label;
    element.setAttribute("aria-label", label);
    element.addEventListener("click", onClick);
    return element;
  };

  const enhance = (host) => {
    if (host.closest(".tf-mermaid")) {
      return;
    }
    const frame = document.createElement("div");
    frame.className = "tf-mermaid";
    const bar = document.createElement("div");
    bar.className = "tf-mermaid__bar";
    const view = document.createElement("div");
    view.className = "tf-mermaid__view";
    host.replaceWith(frame);
    view.append(host);
    frame.append(bar, view);

    let step = ACTUAL;
    const overflows = () => view.scrollWidth > view.clientWidth || view.scrollHeight > view.clientHeight;
    const apply = () => {
      const scale = STEPS[step];
      host.style.transform = scale === 1 ? "" : `scale(${scale})`;
      // A shrunk diagram stays centred. A grown one grows right and down, where the view scrolls.
      host.style.transformOrigin = scale < 1 ? "50% 0" : "0 0";
      // A transform keeps the layout box, so a shrunk diagram would leave empty scroll space below it.
      host.style.marginBottom = scale < 1 ? `${host.offsetHeight * (scale - 1)}px` : "";
      reset.textContent = `${Math.round(scale * 100)}%`;
      const fullScreen = document.fullscreenElement === frame;
      view.style.height =
        fullScreen || scale <= 1
          ? ""
          : `${Math.min(host.offsetHeight * scale, window.innerHeight * MAX_VIEW_HEIGHT)}px`;
      view.classList.toggle("tf-mermaid__view--pannable", overflows());
    };
    const zoomTo = (next) => {
      step = Math.max(0, Math.min(STEPS.length - 1, next));
      apply();
    };

    const reset = button("100%", "Reset zoom", () => zoomTo(ACTUAL));
    bar.append(
      button("−", "Zoom out", () => zoomTo(step - 1)),
      reset,
      button("+", "Zoom in", () => zoomTo(step + 1))
    );
    if (frame.requestFullscreen) {
      bar.append(
        button("⛶", "Full screen", () =>
          document.fullscreenElement === frame ? document.exitFullscreen() : frame.requestFullscreen()
        )
      );
      document.addEventListener("fullscreenchange", apply);
    }

    let drag = null;
    view.addEventListener("pointerdown", (event) => {
      // Pan only a diagram that overflows, so text selection works at 100%.
      if (event.button !== 0 || !overflows()) {
        return;
      }
      // A press on the view's own scrollbar scrolls natively.
      const box = view.getBoundingClientRect();
      if (event.clientX - box.left >= view.clientWidth || event.clientY - box.top >= view.clientHeight) {
        return;
      }
      drag = { x: event.clientX, y: event.clientY, left: view.scrollLeft, top: view.scrollTop };
      view.setPointerCapture(event.pointerId);
      view.classList.add("tf-mermaid__view--dragging");
    });
    view.addEventListener("pointermove", (event) => {
      if (!drag) {
        return;
      }
      view.scrollLeft = drag.left - (event.clientX - drag.x);
      view.scrollTop = drag.top - (event.clientY - drag.y);
    });
    const endDrag = () => {
      drag = null;
      view.classList.remove("tf-mermaid__view--dragging");
    };
    view.addEventListener("pointerup", endDrag);
    view.addEventListener("pointercancel", endDrag);
  };

  const scan = (root) => root.querySelectorAll("div.mermaid").forEach(enhance);

  // Material swaps each <pre class="mermaid"> for a div.mermaid once it renders.
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) {
          continue;
        }
        if (node.matches("div.mermaid")) {
          enhance(node);
        } else {
          scan(node);
        }
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
  scan(document);
})();
