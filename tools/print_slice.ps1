$start = 1198
$end = 1218
$path = "bot_unico.py"
$lines = Get-Content -Path $path
for ($n = $start; $n -le $end; $n++) {
  if ($n -ge 1 -and $n -le $lines.Count) {
    Write-Output ("{0,6}: {1}" -f $n, $lines[$n-1])
  }
}
