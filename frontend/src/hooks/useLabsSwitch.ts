import { useCallback, useState } from 'react';

const LABS_KEY = 'ask-my-documents.show-labs';

// Storage can be unavailable (private windows, blocked site data). The switch
// then starts off and lasts for this page load only.
function readStored() {
  try {
    return window.localStorage.getItem(LABS_KEY) === 'true';
  } catch {
    return false;
  }
}

/**
 * Whether the admin header offers the week-by-week course labs. Off by default:
 * the labs are hidden, not removed, and their #week links work either way.
 */
export function useLabsSwitch() {
  const [showLabs, setShowLabs] = useState(readStored);

  const setLabs = useCallback((next: boolean) => {
    setShowLabs(next);
    try {
      window.localStorage.setItem(LABS_KEY, String(next));
    } catch {
      // Keep the in-memory value.
    }
  }, []);

  return { showLabs, setLabs };
}
