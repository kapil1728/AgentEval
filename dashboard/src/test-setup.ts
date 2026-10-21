import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

afterEach(cleanup)

class TestResizeObserver implements ResizeObserver {
	constructor(private readonly callback: ResizeObserverCallback) {}

	observe(target: Element): void {
		this.callback(
			[{ target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry],
			this,
		)
	}

	unobserve(): void {}

	disconnect(): void {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
	configurable: true,
	value: TestResizeObserver,
})
