import "./style.css";

import { Map } from "maplibre-gl";
import axios from "axios";

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

// Load config and initialize map
(async () => {
  let mapConfig = { center: [0, 0], zoom: 0 };
  let defaultCenter = [0, 0];
  let defaultZoom = 0;
  let hasConfigDefaults = false;
  let zimName = null;
  let storageKey = null;

  try {
    const response = await axios.get(toAbsolute("./content/config.json"));
    const config = response.data;

    console.log(config)
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
  } catch (error) {
    console.warn("Could not load config.json, using defaults:", error);
  }

  const map = new Map({
    container: "map",
    center: mapConfig.center,
    zoom: mapConfig.zoom,
    transformRequest: (url) => {
      return { url: toAbsolute(url) };
    },
  });

  map.setStyle("./styles/liberty", {
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

  // Coordinates and zoom display functionality
  const resetButton = document.getElementById("resetButton");
  const coordsButton = document.getElementById("coordsButton");
  const coordsPopover = document.getElementById("coordsPopover");
  const zoomLevel = document.getElementById("zoomLevel");
  const latitude = document.getElementById("latitude");
  const longitude = document.getElementById("longitude");

  // Show reset button only after map loads and if config has defaults
  map.on("load", () => {
    if (hasConfigDefaults) {
      resetButton.style.display = "flex";
      resetButton.addEventListener("click", () => {
        map.flyTo({
          center: defaultCenter,
          zoom: defaultZoom,
          duration: 1000,
        });
      });
    }
  });

  // Toggle popover visibility
  coordsButton.addEventListener("click", () => {
    coordsPopover.classList.toggle("visible");
  });

  // Close popover when clicking outside
  document.addEventListener("click", (event) => {
    if (
      !coordsButton.contains(event.target) &&
      !coordsPopover.contains(event.target)
    ) {
      coordsPopover.classList.remove("visible");
    }
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
    zoomLevel.textContent = map.getZoom().toFixed(2);
    latitude.textContent = center.lat.toFixed(6);
    longitude.textContent = center.lng.toFixed(6);

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

  // Initial update
  updateCoordinates();
})();
