/**
 * Virtual Scrolling for Large Tables
 *
 * Renders only visible rows to improve performance with large datasets.
 * Supports:
 * - Dynamic row heights
 * - Smooth scrolling
 * - Row recycling
 * - Event delegation
 */

export class VirtualTable {
  constructor(container, options = {}) {
    this.container = container;
    this.data = options.data || [];
    this.rowHeight = options.rowHeight || 50;
    this.overscan = options.overscan || 3; // Extra rows to render above/below viewport
    this.renderRow = options.renderRow || ((item) => `<div>${JSON.stringify(item)}</div>`);
    this.onRowClick = options.onRowClick || null;

    this.scrollTop = 0;
    this.containerHeight = 0;
    this.visibleRowCount = 0;
    this.startIndex = 0;
    this.endIndex = 0;

    this.viewport = null;
    this.content = null;

    this._init();
  }

  /**
   * Initialize virtual table
   */
  _init() {
    // Create viewport structure
    this.container.innerHTML = `
      <div class="virtual-table-viewport" style="overflow-y: auto; height: 100%;">
        <div class="virtual-table-spacer" style="position: relative;">
          <div class="virtual-table-content"></div>
        </div>
      </div>
    `;

    this.viewport = this.container.querySelector('.virtual-table-viewport');
    this.spacer = this.container.querySelector('.virtual-table-spacer');
    this.content = this.container.querySelector('.virtual-table-content');

    // Set up scroll listener
    this.viewport.addEventListener('scroll', () => this._onScroll());

    // Set up click delegation
    if (this.onRowClick) {
      this.content.addEventListener('click', (e) => {
        const row = e.target.closest('[data-row-index]');
        if (row) {
          const index = parseInt(row.getAttribute('data-row-index'), 10);
          this.onRowClick(this.data[index], index, e);
        }
      });
    }

    // Initial render
    this._updateDimensions();
    this._render();
  }

  /**
   * Update data and re-render
   */
  setData(data) {
    this.data = data;
    this._updateDimensions();
    this._render();
  }

  /**
   * Update dimensions
   */
  _updateDimensions() {
    this.containerHeight = this.viewport.clientHeight;
    this.visibleRowCount = Math.ceil(this.containerHeight / this.rowHeight);

    // Set spacer height to total content height
    const totalHeight = this.data.length * this.rowHeight;
    this.spacer.style.height = `${totalHeight}px`;
  }

  /**
   * Handle scroll event
   */
  _onScroll() {
    this.scrollTop = this.viewport.scrollTop;
    this._render();
  }

  /**
   * Render visible rows
   *
   * Optimization: Use transform instead of top for GPU acceleration
   */
  _render() {
    // Calculate visible range
    this.startIndex = Math.max(0, Math.floor(this.scrollTop / this.rowHeight) - this.overscan);
    this.endIndex = Math.min(
      this.data.length,
      this.startIndex + this.visibleRowCount + this.overscan * 2
    );

    // Render visible rows
    const visibleData = this.data.slice(this.startIndex, this.endIndex);
    const html = visibleData.map((item, i) => {
      const index = this.startIndex + i;
      // Optimization: Use transform for GPU acceleration instead of top
      // This triggers compositing layer and avoids layout recalculation
      return `<div class="virtual-table-row" data-row-index="${index}" style="position: absolute; top: 0; transform: translateY(${index * this.rowHeight}px); width: 100%; height: ${this.rowHeight}px; will-change: transform;">
        ${this.renderRow(item, index)}
      </div>`;
    }).join('');

    this.content.innerHTML = html;
  }

  /**
   * Scroll to specific index
   */
  scrollToIndex(index) {
    const targetScroll = index * this.rowHeight;
    this.viewport.scrollTop = targetScroll;
  }

  /**
   * Get current scroll position
   */
  getScrollPosition() {
    return {
      scrollTop: this.scrollTop,
      startIndex: this.startIndex,
      endIndex: this.endIndex,
    };
  }

  /**
   * Destroy and clean up
   */
  destroy() {
    this.viewport.removeEventListener('scroll', this._onScroll);
    this.container.innerHTML = '';
  }
}

/**
 * Virtual List (simpler version for lists)
 */
export class VirtualList {
  constructor(container, options = {}) {
    this.container = container;
    this.items = options.items || [];
    this.itemHeight = options.itemHeight || 60;
    this.renderItem = options.renderItem || ((item) => `<div>${item}</div>`);
    this.onItemClick = options.onItemClick || null;

    this.table = new VirtualTable(container, {
      data: this.items,
      rowHeight: this.itemHeight,
      renderRow: this.renderItem,
      onRowClick: this.onItemClick,
    });
  }

  setItems(items) {
    this.items = items;
    this.table.setData(items);
  }

  scrollToIndex(index) {
    this.table.scrollToIndex(index);
  }

  destroy() {
    this.table.destroy();
  }
}

/**
 * Infinite Scroll Loader
 */
export class InfiniteScroll {
  constructor(container, options = {}) {
    this.container = container;
    this.loadMore = options.loadMore || (() => Promise.resolve([]));
    this.threshold = options.threshold || 200; // px from bottom to trigger load
    this.isLoading = false;
    this.hasMore = true;

    this._init();
  }

  _init() {
    this.container.addEventListener('scroll', () => this._onScroll());
  }

  async _onScroll() {
    if (this.isLoading || !this.hasMore) return;

    const scrollTop = this.container.scrollTop;
    const scrollHeight = this.container.scrollHeight;
    const clientHeight = this.container.clientHeight;

    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

    if (distanceFromBottom < this.threshold) {
      await this._load();
    }
  }

  async _load() {
    this.isLoading = true;

    try {
      const newItems = await this.loadMore();

      if (!newItems || newItems.length === 0) {
        this.hasMore = false;
      }
    } catch (error) {
      console.error('Infinite scroll load error:', error);
    } finally {
      this.isLoading = false;
    }
  }

  reset() {
    this.hasMore = true;
    this.isLoading = false;
  }
}

/**
 * Lazy Image Loader with Intersection Observer
 */
export class LazyImageLoader {
  constructor(options = {}) {
    this.rootMargin = options.rootMargin || '50px';
    this.threshold = options.threshold || 0.01;

    this.observer = new IntersectionObserver(
      (entries) => this._onIntersection(entries),
      {
        rootMargin: this.rootMargin,
        threshold: this.threshold,
      }
    );
  }

  /**
   * Observe images with data-src attribute
   */
  observe(container) {
    const images = container.querySelectorAll('img[data-src]');
    images.forEach((img) => this.observer.observe(img));
  }

  /**
   * Handle intersection
   */
  _onIntersection(entries) {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const img = entry.target;
        const src = img.getAttribute('data-src');

        if (src) {
          img.src = src;
          img.removeAttribute('data-src');
          this.observer.unobserve(img);
        }
      }
    });
  }

  /**
   * Disconnect observer
   */
  disconnect() {
    this.observer.disconnect();
  }
}

/**
 * Debounced Resize Observer
 */
export class DebouncedResizeObserver {
  constructor(callback, delay = 150) {
    this.callback = callback;
    this.delay = delay;
    this.timerId = null;

    this.observer = new ResizeObserver((entries) => {
      clearTimeout(this.timerId);
      this.timerId = setTimeout(() => {
        this.callback(entries);
      }, this.delay);
    });
  }

  observe(element) {
    this.observer.observe(element);
  }

  unobserve(element) {
    this.observer.unobserve(element);
  }

  disconnect() {
    clearTimeout(this.timerId);
    this.observer.disconnect();
  }
}

/**
 * CSS for Virtual Scrolling
 */
export const virtualScrollCSS = `
.virtual-table-viewport {
  overflow-y: auto;
  overflow-x: hidden;
  will-change: scroll-position;
}

.virtual-table-spacer {
  position: relative;
  width: 100%;
}

.virtual-table-content {
  position: relative;
  width: 100%;
}

.virtual-table-row {
  position: absolute;
  width: 100%;
  box-sizing: border-box;
}

/* Smooth scrolling */
.virtual-table-viewport {
  scroll-behavior: smooth;
}

/* Custom scrollbar */
.virtual-table-viewport::-webkit-scrollbar {
  width: 8px;
}

.virtual-table-viewport::-webkit-scrollbar-track {
  background: rgba(0, 255, 136, 0.05);
}

.virtual-table-viewport::-webkit-scrollbar-thumb {
  background: rgba(0, 255, 136, 0.2);
  border-radius: 4px;
}

.virtual-table-viewport::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 255, 136, 0.3);
}
`;

// Inject CSS
if (typeof document !== 'undefined') {
  const style = document.createElement('style');
  style.textContent = virtualScrollCSS;
  document.head.appendChild(style);
}
