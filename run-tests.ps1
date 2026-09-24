param(
    [string]$Dir = "test",
    [switch]$Headed,
    [switch]$NoServe,
    [switch]$ServeOnly,
    [int]$Port = 8080,
    [switch]$NoBrowser
)

$argsList = @("--dir", $Dir)
if ($Headed) {
    $argsList += "--headed"
}
if ($NoServe) {
    $argsList += "--no-serve"
}
if ($ServeOnly) {
    $argsList += "--serve-only"
}
if ($Port -ne 8080) {
    $argsList += @("--port", $Port)
}
if ($NoBrowser) {
    $argsList += "--no-browser"
}

python "$PSScriptRoot\run_tests.py" @argsList
