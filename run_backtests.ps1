$python = "C:/Users/Paul/Apps/crypto-mvp/.venv/Scripts/python.exe"
$script = "scripts/backtest.py"

$runs = @(
    # Regime 1 — COVID crash (Mar–Apr 2020, $10k→$4k→$7k)
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=120; tp=20 },
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=120; tp=10 },
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=120; tp=5  },
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=180; tp=20 },
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=180; tp=10 },
    @{ regime="covid";  start="2020-03-01"; end="2020-04-30"; bid=80;  tp=5  },

    # Regime 2 — Bull run peak (Oct–Nov 2021, $43k→$68k)
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=120; tp=20 },
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=120; tp=10 },
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=120; tp=5  },
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=180; tp=20 },
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=180; tp=10 },
    @{ regime="bull";   start="2021-10-01"; end="2021-11-30"; bid=80;  tp=5  },

    # Regime 3 — Bear market collapse (May–Jul 2022, $38k→$19k)
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=120; tp=20 },
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=120; tp=10 },
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=120; tp=5  },
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=180; tp=20 },
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=180; tp=10 },
    @{ regime="bear";   start="2022-05-01"; end="2022-07-31"; bid=80;  tp=5  },

    # Regime 4 — Slow recovery / ranging (Jan–Mar 2023, $16k→$28k)
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=120; tp=20 },
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=120; tp=10 },
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=120; tp=5  },
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=180; tp=20 },
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=180; tp=10 },
    @{ regime="range";  start="2023-01-01"; end="2023-03-31"; bid=80;  tp=5  },

    # Regime 5 — ETF run-up (Oct–Dec 2024, $60k→$109k)
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=120; tp=20 },
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=120; tp=10 },
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=120; tp=5  },
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=180; tp=20 },
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=180; tp=10 },
    @{ regime="etf";    start="2024-10-01"; end="2024-12-31"; bid=80;  tp=5  },

    # Regime 6 — Current pullback (Jan–Mar 2025, $109k→$71k)
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=120; tp=20 },
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=120; tp=10 },
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=120; tp=5  },
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=180; tp=20 },
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=180; tp=10 },
    @{ regime="now";    start="2025-01-01"; end="2025-03-13"; bid=80;  tp=5  }
)

$results = @()
$total = $runs.Count
$i = 0

foreach ($run in $runs) {
    $i++
    $label = "$($run.regime)_bo$($run.bid)_tp$($run.tp)"
    $outfile = "backtest_results/$label.csv"
    $null = New-Item -ItemType Directory -Force -Path "backtest_results"

    Write-Host "[$i/$total] $label" -ForegroundColor Cyan

    $output = & $python $script `
        --start $run.start `
        --end   $run.end `
        --bid-offset $run.bid `
        --target-profit $run.tp `
        --output $outfile 2>&1

    # Extract summary lines
    $fills    = ($output | Where-Object { $_ -match "^Total fills:" }   | Select-Object -First 1) -replace "Total fills:\s+",""
    $net      = ($output | Where-Object { $_ -match "^Net PnL:" }       | Select-Object -First 1) -replace "Net PnL:\s+",""
    $ret      = ($output | Where-Object { $_ -match "^Return:" }        | Select-Object -First 1) -replace "Return:\s+",""
    $dd       = ($output | Where-Object { $_ -match "^Max drawdown:" }  | Select-Object -First 1) -replace "Max drawdown:\s+",""
    $fillLine = ($output | Where-Object { $_ -match "^Total fills:" }   | Select-Object -First 1)
    $buys     = if ($fillLine -match "\((\d+) buys") { $Matches[1] } else { "?" }
    $sells    = if ($fillLine -match "(\d+) sells\)") { $Matches[1] } else { "?" }

    $results += [PSCustomObject]@{
        Regime        = $run.regime
        BidOffset     = $run.bid
        TargetProfit  = $run.tp
        Fills         = ($fills -split " ")[0]
        Buys          = $buys
        Sells         = $sells
        NetPnL        = $net
        Return        = $ret
        MaxDrawdown   = $dd
    }

    Write-Host "  fills=$($results[-1].Fills) buys=$buys sells=$sells net=$net ret=$ret dd=$dd"
}

# Print full results table
Write-Host ""
Write-Host "===== FULL RESULTS =====" -ForegroundColor Green
$results | Format-Table -AutoSize

# Save to CSV
$results | Export-Csv -Path "backtest_results/summary.csv" -NoTypeInformation
Write-Host "Saved to backtest_results/summary.csv" -ForegroundColor Green

# Best per regime
Write-Host ""
Write-Host "===== BEST CONFIG PER REGIME (by Net PnL) =====" -ForegroundColor Yellow
$results | Group-Object Regime | ForEach-Object {
    $best = $_.Group | Sort-Object { [double]($_.NetPnL -replace '[^0-9.\-]','') } -Descending | Select-Object -First 1
    Write-Host "  $($_.Name): bid=$($best.BidOffset) tp=$($best.TargetProfit) → net=$($best.NetPnL) ret=$($best.Return)"
}

# Best overall (most regime wins)
Write-Host ""
Write-Host "===== CONFIG WINS BY REGIME =====" -ForegroundColor Yellow
$results | Group-Object { "$($_.BidOffset)/$($_.TargetProfit)" } | ForEach-Object {
    $wins = ($_.Group | Where-Object { [double]($_.NetPnL -replace '[^0-9.\-]','') -gt 0 }).Count
    Write-Host "  bid=$( ($_.Name -split '/')[0] ) tp=$( ($_.Name -split '/')[1] ): $wins/6 regimes positive"
}