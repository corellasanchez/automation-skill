param(
    [string]$Dir = "test",
    [switch]$Headed
)

$argsList = @("--dir", $Dir)
if ($Headed) {
    $argsList += "--headed"
}

python "$PSScriptRoot\run_tests.py" @argsList
