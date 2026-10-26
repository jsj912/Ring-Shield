import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver; Radix primitives (checkbox, slider) measure themselves with it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
