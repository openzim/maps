import "./style.css";

import { Map, ScaleControl } from "maplibre-gl";
import maplibre from "maplibre-gl";

const isWebGLAvailable = () => {
  try {
    const canvas = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
};

const isFetchAPIAvailable = async () => {
  try {
    // any URL (even missing content) would work, but better to fetch something useful
    await fetch("./content/config.json");
    return true;
  } catch {
    return false;
  }
};

const getMissingCapabilities = async () => {
  const missing = [];
  if (!isWebGLAvailable()) missing.push("WebGL");
  if (!(await isFetchAPIAvailable())) missing.push("Fetch API");
  return missing;
};

const showCapabilityError = (missing) => {
  if (missing.length > 0) {
    const techno1 = document.getElementById("techno1");
    techno1.innerHTML = missing[0];
  }
  if (missing.length > 1) {
    const techno2 = document.getElementById("techno2");
    techno2.innerHTML = missing[1];
  } else {
    const andBlock = document.getElementById("and");
    andBlock.style.display = "none";
  }
};

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

const flyTo = (map, center, zoom) => {
  if (center !== undefined) {
    if (zoom !== undefined) {
      map.flyTo({
        center: center,
        zoom: zoom,
        duration: 1000,
      });
    } else {
      // zoom-out as much as possible while keeping expected center
      map.fitBounds(map.getMaxBounds(), {
        center: center,
        duration: 1000,
      });
    }
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
  const loadingDiv = document.getElementById("loading");
  const mapDiv = document.getElementById("map");
  const errorDiv = document.getElementById("error");

  const missingCapabilities = await getMissingCapabilities();
  if (missingCapabilities.length > 0) {
    showCapabilityError(missingCapabilities);
    loadingDiv.style.display = "none";
    errorDiv.style.display = "block";
    return;
  }

  maplibre
    .setRTLTextPlugin("./assets/mapbox-gl-rtl-text.js", true)
    .then(() => console.log("RTL plugin loaded"))
    .catch((err) => console.error("RTL plugin error:", err));

  let defaultCenter = undefined;
  let defaultZoom = undefined;
  let mapConfig = { center: undefined, zoom: undefined, bounds: undefined };
  let zimName = null;
  let storageKey = null;
  let maxZoom = 18;

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
    }
    if (config.zoom !== undefined) {
      defaultZoom = config.zoom;
    }
    if (config.boundingBox) {
      mapConfig.bounds = config.boundingBox;
    }
    if (config.maxZoom !== undefined) {
      maxZoom = config.maxZoom;
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

      // Use saved view if available, otherwise use default values
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

  loadingDiv.style.display = "none";
  mapDiv.style.display = "block";

  const map = new Map({
    container: "map",
    maxZoom: maxZoom,
    transformRequest: (url) => {
      return { url: toAbsolute(url) };
    },
  });

  window.__openzim_map = map; // Save in window, useful for debug purposes

  if (mapConfig.bounds !== undefined) {
    map.setMaxBounds(mapConfig.bounds);
  }

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
    if (defaultCenter !== undefined) {
      resetButton.style.display = "flex";
    }
    flyTo(map, mapConfig.center, mapConfig.zoom);
    // This is a bug, but for some reason sometimes the first flyTo doesn't work
    // and when we retry 1 second later "it works"
    setTimeout(() => {
      flyTo(map, mapConfig.center, mapConfig.zoom);
    }, 1000);
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
    flyTo(map, defaultCenter, defaultZoom);
  });

  // About button functionality
  aboutButton.addEventListener("click", () => {
    window.location.href = toAbsolute("./content/about.html");
  });

  // Debounce function for updating coordinates
  const debounce = (func, wait) => {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        window.clearTimeout(timeout);
        func(...args);
      };
      window.clearTimeout(timeout);
      timeout = window.setTimeout(later, wait);
    };
  };

  // Update coordinates display and save view to localStorage
  const updateCoordinates = () => {
    const center = map.getCenter();

    // Save current view to localStorage if we have a storage key
    if (storageKey) {
      try {
        const view = {
          center: [center.lng, center.lat],
          zoom: map.getZoom(),
        };
        window.localStorage.setItem(storageKey, JSON.stringify(view));
      } catch (e) {
        console.warn("Could not save view to localStorage:", e);
      }
    }
  };

  // Debounced update function (100ms delay)
  const debouncedUpdateCoordinates = debounce(updateCoordinates, 100);

  // Listen to map move and zoom events
  map.on("move", debouncedUpdateCoordinates);
  map.on("zoom", debouncedUpdateCoordinates);
})();
