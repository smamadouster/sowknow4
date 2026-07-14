'use client';

import { useState, useEffect } from 'react';

/**
 * Debounce a value by `delay` milliseconds.
 *
 * Returns the latest value after the specified delay has elapsed without
 * the input changing. Useful for delaying API calls from search inputs.
 */
export function useDebounce<T>(value: T, delay = 400): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

export default useDebounce;
