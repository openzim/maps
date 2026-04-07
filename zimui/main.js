import "./style.css";

import { Map, ScaleControl } from "maplibre-gl";
import maplibre from "maplibre-gl";

maplibre
  .setRTLTextPlugin("./assets/mapbox-gl-rtl-text.js", true)
  .then(() => console.log("RTL plugin loaded"))
  .catch((err) => console.error("RTL plugin error:", err));

const baseUrl =
  window.location.origin +
  window.location.pathname.substring(
    0,
    window.location.pathname.lastIndexOf("/"),
  );

const toAbsolute = (url) => {
  if (!url || url.indexOf("://") >= 0) {
    return url;
  }

  if (url.startsWith("./")) {
    return baseUrl + "/" + url.substring(2);
  } else if (url.startsWith("../")) {
    const parts = baseUrl.split("/");
    let urlParts = url.split("/");
    while (urlParts[0] === "..") {
      parts.pop();
      urlParts.shift();
    }
    return parts.join("/") + "/" + urlParts.join("/");
  } else if (!url.startsWith("/")) {
    return baseUrl + "/" + url;
  } else {
    return window.location.origin + url;
  }
};

// Parse URL fragment parameters for lat, lon, zoom
const parseUrlFragment = () => {
  const fragment = window.location.hash.substring(1);
  if (!fragment) return null;

  const params = new URLSearchParams(fragment);
  const lat = params.get("lat");
  const lon = params.get("lon");
  const zoom = params.get("zoom");

  if (lat !== null && lon !== null && zoom !== null) {
    const latNum = parseFloat(lat);
    const lonNum = parseFloat(lon);
    const zoomNum = parseFloat(zoom);

    if (
      !isNaN(latNum) &&
      !isNaN(lonNum) &&
      !isNaN(zoomNum) &&
      latNum >= -90 &&
      latNum <= 90 &&
      lonNum >= -180 &&
      lonNum <= 180 &&
      zoomNum >= 0 &&
      zoomNum <= 14
    ) {
      return {
        center: [lonNum, latNum],
        zoom: zoomNum,
      };
    }
  }

  return null;
};

// Load config and initialize map
(async () => {
  let mapConfig = { center: [0, 0], zoom: 0 };
  let defaultCenter = [0, 0];
  let defaultZoom = 0;
  let hasConfigDefaults = false;
  let zimName = null;
  let storageKey = null;

  try {
    const response = await fetch("./content/config.json");
    if (!response.ok) {
      throw new Error(`fetch error: ${response.status}`);
    }
    const config = await response.json();

    // Get zim_name for localStorage key
    if (config.zimName) {
      zimName = config.zimName;
      storageKey = `openzim$${zimName}$default_view`;
    }

    // Store default center and zoom from config
    if (config.center) {
      defaultCenter = config.center;
      hasConfigDefaults = true;
    }
    if (config.zoom !== undefined) {
      defaultZoom = config.zoom;
      hasConfigDefaults = true;
    }

    // Check for URL fragment parameters (highest priority)
    const urlParams = parseUrlFragment();
    if (urlParams) {
      mapConfig.center = urlParams.center;
      mapConfig.zoom = urlParams.zoom;
    } else {
      // Check for saved view in localStorage
      let savedView = null;
      if (storageKey) {
        try {
          savedView = JSON.parse(window.localStorage.getItem(storageKey));
        } catch (e) {
          console.warn("Could not parse saved view from localStorage:", e);
        }
      }

      // Use saved view if available, otherwise use config values
      if (savedView && savedView.center && savedView.zoom !== undefined) {
        mapConfig.center = savedView.center;
        mapConfig.zoom = savedView.zoom;
      } else {
        mapConfig.center = defaultCenter;
        mapConfig.zoom = defaultZoom;
      }
    }
  } catch (error) {
    console.warn("Could not load config.json, using defaults:", error);
  }

  const map = new Map({
    container: "map",
    center: mapConfig.center,
    zoom: mapConfig.zoom,
    maxZoom: 18,
    transformRequest: (url) => {
      return { url: toAbsolute(url) };
    },
  });
  const scale = new ScaleControl({ unit: "metric" });
  map.addControl(scale, "bottom-right");

  const setMapStyle = (styleName) => {
    map.setStyle(`./assets/${styleName}`, {
      validate: false,
      transformStyle: (previousStyle, nextStyle) => {
        return {
          ...nextStyle,
          glyphs: toAbsolute(nextStyle.glyphs),
          sprite: toAbsolute(nextStyle.sprite),
          sources: Object.fromEntries(
            Object.entries(nextStyle.sources || {}).map(([key, source]) => {
              const updatedSource = { ...source };

              if (source.url) {
                updatedSource.url = toAbsolute(source.url);
              }

              if (source.tiles && Array.isArray(source.tiles)) {
                updatedSource.tiles = source.tiles.map(toAbsolute);
              }

              if (source.data && typeof source.data === "string") {
                updatedSource.data = toAbsolute(source.data);
              }

              return [key, updatedSource];
            }),
          ),
        };
      },
    });
  };

  // Listen for prefers-color-scheme changes
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", updateTheme);

  // Automatically switch between kiwix-light and kiwix-dark themes based on
  // UA prefers-color-scheme value
  function updateTheme() {
    let currentStyle = "kiwix-light";
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      currentStyle = "kiwix-dark";
    }
    setMapStyle(currentStyle);
  }

  // Set initial theme at map load
  updateTheme();

  // UI elements
  const buttonContainer = document.querySelector(".button-container");
  const resetButton = document.getElementById("resetButton");
  const aboutButton = document.getElementById("aboutButton");

  // Show button container and reset button only after map loads if config has defaults
  map.on("load", () => {
    buttonContainer.classList.add("visible");
    if (hasConfigDefaults) {
      resetButton.style.display = "flex";
    }
  });

  const scaleElement = scale._container;
  scaleElement.style.cursor = "pointer";
  scaleElement.title = "Toggle unit: metric/imperial";

  // Toggle scale unit on click
  scaleElement.addEventListener("click", () => {
    const currentUnit = scale.options.unit;
    const newUnit = currentUnit === "metric" ? "imperial" : "metric";
    scale.setUnit(newUnit);
  });

  // Reset button functionality
  resetButton.addEventListener("click", () => {
    map.flyTo({
      center: defaultCenter,
      zoom: defaultZoom,
      duration: 1000,
    });
  });

  // About button functionality
  aboutButton.addEventListener("click", () => {
    window.location.href = toAbsolute("./content/about.html");
  });
})();
