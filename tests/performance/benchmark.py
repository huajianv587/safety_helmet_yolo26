"""
Performance Benchmark Suite

Comprehensive performance testing for the optimization work.
"""

import time
import statistics
from typing import Callable, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BenchmarkResult:
    """Benchmark result for a single test"""
    name: str
    iterations: int
    total_time: float
    mean_time: float
    median_time: float
    p95_time: float
    p99_time: float
    min_time: float
    max_time: float
    throughput: float  # ops/sec
    times: list[float] = field(default_factory=list)


class PerformanceBenchmark:
    """
    Performance benchmark runner.

    Usage:
        benchmark = PerformanceBenchmark()
        result = benchmark.run("Test Name", test_function, iterations=100)
        print(result)
    """

    def __init__(self):
        self.results: list[BenchmarkResult] = []

    def run(
        self,
        name: str,
        func: Callable,
        iterations: int = 100,
        warmup: int = 10,
        *args,
        **kwargs
    ) -> BenchmarkResult:
        """
        Run benchmark for a function.

        Args:
            name: Test name
            func: Function to benchmark
            iterations: Number of iterations
            warmup: Number of warmup iterations
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            BenchmarkResult
        """
        print(f"[Benchmark] Running: {name} ({iterations} iterations)")

        # Warmup
        for _ in range(warmup):
            func(*args, **kwargs)

        # Actual benchmark
        times = []
        for i in range(iterations):
            start = time.perf_counter()
            func(*args, **kwargs)
            end = time.perf_counter()
            times.append(end - start)

        # Calculate statistics
        total_time = sum(times)
        mean_time = statistics.mean(times)
        median_time = statistics.median(times)
        min_time = min(times)
        max_time = max(times)

        sorted_times = sorted(times)
        p95_time = sorted_times[int(len(sorted_times) * 0.95)]
        p99_time = sorted_times[int(len(sorted_times) * 0.99)]

        throughput = iterations / total_time

        result = BenchmarkResult(
            name=name,
            iterations=iterations,
            total_time=total_time,
            mean_time=mean_time,
            median_time=median_time,
            p95_time=p95_time,
            p99_time=p99_time,
            min_time=min_time,
            max_time=max_time,
            throughput=throughput,
            times=times
        )

        self.results.append(result)
        print(f"[Benchmark] Completed: {name} - Mean: {mean_time*1000:.2f}ms, P95: {p95_time*1000:.2f}ms")

        return result

    def compare(self, baseline_name: str, optimized_name: str) -> dict[str, Any]:
        """
        Compare two benchmark results.

        Args:
            baseline_name: Name of baseline test
            optimized_name: Name of optimized test

        Returns:
            Comparison dictionary
        """
        baseline = next((r for r in self.results if r.name == baseline_name), None)
        optimized = next((r for r in self.results if r.name == optimized_name), None)

        if not baseline or not optimized:
            raise ValueError("Both baseline and optimized results must exist")

        improvement_mean = ((baseline.mean_time - optimized.mean_time) / baseline.mean_time) * 100
        improvement_p95 = ((baseline.p95_time - optimized.p95_time) / baseline.p95_time) * 100
        throughput_increase = ((optimized.throughput - baseline.throughput) / baseline.throughput) * 100

        return {
            "baseline": baseline_name,
            "optimized": optimized_name,
            "improvement_mean_pct": improvement_mean,
            "improvement_p95_pct": improvement_p95,
            "throughput_increase_pct": throughput_increase,
            "baseline_mean_ms": baseline.mean_time * 1000,
            "optimized_mean_ms": optimized.mean_time * 1000,
            "baseline_p95_ms": baseline.p95_time * 1000,
            "optimized_p95_ms": optimized.p95_time * 1000,
        }

    def generate_report(self) -> str:
        """Generate markdown report of all benchmarks."""
        report = ["# Performance Benchmark Report", ""]
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("")
        report.append("## Results")
        report.append("")
        report.append("| Test Name | Iterations | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Throughput (ops/s) |")
        report.append("|-----------|------------|-----------|-------------|----------|----------|--------------------|")

        for result in self.results:
            report.append(
                f"| {result.name} | {result.iterations} | "
                f"{result.mean_time*1000:.2f} | {result.median_time*1000:.2f} | "
                f"{result.p95_time*1000:.2f} | {result.p99_time*1000:.2f} | "
                f"{result.throughput:.2f} |"
            )

        return "\n".join(report)


# ============================================================================
# Specific Benchmark Tests
# ============================================================================

def benchmark_cache_performance():
    """Benchmark cache system performance."""
    from helmet_monitoring.api.cache_manager import get_cache_manager, CacheTier

    benchmark = PerformanceBenchmark()
    cache = get_cache_manager()

    # Test data
    test_key = ("test", "key")
    test_value = {"data": "test" * 100}

    # Benchmark cache set
    benchmark.run(
        "Cache Set",
        lambda: cache.set(test_key, test_value, CacheTier.SUMMARIES),
        iterations=1000
    )

    # Benchmark cache get (hit)
    cache.set(test_key, test_value, CacheTier.SUMMARIES)
    benchmark.run(
        "Cache Get (Hit)",
        lambda: cache.get(test_key, CacheTier.SUMMARIES),
        iterations=1000
    )

    # Benchmark cache get (miss)
    benchmark.run(
        "Cache Get (Miss)",
        lambda: cache.get(("nonexistent", "key"), CacheTier.SUMMARIES),
        iterations=1000
    )

    return benchmark


def benchmark_repository_performance():
    """Benchmark repository query performance."""
    from helmet_monitoring.storage.indexed_repository import IndexedLocalAlertRepository
    from helmet_monitoring.storage.repository import LocalAlertRepository
    from helmet_monitoring.core.config import load_settings

    benchmark = PerformanceBenchmark()
    settings = load_settings()
    runtime_dir = settings.resolve_path(settings.persistence.runtime_dir)

    # Create repositories
    indexed_repo = IndexedLocalAlertRepository(runtime_dir)
    standard_repo = LocalAlertRepository(runtime_dir)

    # Benchmark list_alerts
    benchmark.run(
        "Standard Repository - List Alerts",
        lambda: standard_repo.list_alerts(limit=100),
        iterations=50
    )

    benchmark.run(
        "Indexed Repository - List Alerts",
        lambda: indexed_repo.list_alerts(limit=100),
        iterations=50
    )

    # Compare
    comparison = benchmark.compare(
        "Standard Repository - List Alerts",
        "Indexed Repository - List Alerts"
    )

    print("\n=== Repository Performance Comparison ===")
    print(f"Mean improvement: {comparison['improvement_mean_pct']:.1f}%")
    print(f"P95 improvement: {comparison['improvement_p95_pct']:.1f}%")
    print(f"Throughput increase: {comparison['throughput_increase_pct']:.1f}%")

    return benchmark


def benchmark_dashboard_aggregation():
    """Benchmark dashboard aggregation performance."""
    from helmet_monitoring.services.optimized_dashboard import OptimizedDashboardAggregator
    from helmet_monitoring.storage.repository import build_repository
    from helmet_monitoring.core.config import load_settings

    benchmark = PerformanceBenchmark()
    settings = load_settings()
    repository = build_repository(settings)

    aggregator = OptimizedDashboardAggregator(settings, repository)

    # Benchmark overview generation
    benchmark.run(
        "Dashboard Overview (Optimized)",
        lambda: aggregator.build_overview_payload(days=7),
        iterations=50
    )

    return benchmark


def benchmark_api_endpoints():
    """Benchmark API endpoint performance."""
    import requests

    benchmark = PerformanceBenchmark()
    base_url = "http://localhost:8000"

    # Benchmark list alerts
    benchmark.run(
        "API - List Alerts",
        lambda: requests.get(f"{base_url}/api/v1/alerts?limit=10"),
        iterations=100
    )

    # Benchmark dashboard overview
    benchmark.run(
        "API - Dashboard Overview",
        lambda: requests.get(f"{base_url}/api/v1/platform-overview"),
        iterations=100
    )

    # Benchmark cameras list
    benchmark.run(
        "API - List Cameras",
        lambda: requests.get(f"{base_url}/api/v1/cameras"),
        iterations=100
    )

    return benchmark


def run_full_benchmark_suite():
    """Run complete benchmark suite."""
    print("=" * 80)
    print("PERFORMANCE BENCHMARK SUITE")
    print("=" * 80)
    print()

    all_results = []

    # Cache benchmarks
    print("\n--- Cache Performance ---")
    cache_bench = benchmark_cache_performance()
    all_results.extend(cache_bench.results)

    # Repository benchmarks
    print("\n--- Repository Performance ---")
    repo_bench = benchmark_repository_performance()
    all_results.extend(repo_bench.results)

    # Dashboard benchmarks
    print("\n--- Dashboard Performance ---")
    dashboard_bench = benchmark_dashboard_aggregation()
    all_results.extend(dashboard_bench.results)

    # Generate combined report
    combined = PerformanceBenchmark()
    combined.results = all_results

    report = combined.generate_report()

    # Save report
    with open("performance_benchmark_report.md", "w") as f:
        f.write(report)

    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETE")
    print("=" * 80)
    print(f"\nReport saved to: performance_benchmark_report.md")

    return combined


if __name__ == "__main__":
    run_full_benchmark_suite()
