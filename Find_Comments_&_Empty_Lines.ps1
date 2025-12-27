$excludedDirNames = @(
    'binaries',
    'config',
    'logs',
    'mp3',
    '!!!_Ouput_Video_Files_!!!'   # matches your actual folder spelling
)
$excludedFileNames = @(
    'app.py',
    'Installer.ps1',
    'project_structure.txt'
)
$allowedExtensions = @(
    '.py','.txt','.md','.json','.ini','.cfg','.yml','.yaml',
    '.js','.ts','.html','.css','.qss','.bat','.cmd','.ps1'
)
Get-ChildItem -Recurse -File | Where-Object {
    if ($excludedFileNames -contains $_.Name) { return $false }
    if ($allowedExtensions -notcontains $_.Extension.ToLowerInvariant()) { return $false }
    $dirParts = $_.DirectoryName -split '[\\/]'   # handles Windows + mixed slashes
    foreach ($d in $excludedDirNames) {
        if ($dirParts -contains $d) { return $false }
    }
    return $true
} | ForEach-Object {
    $file  = $_.FullName
    $lines = Get-Content -LiteralPath $file
    for ($i = 0; $i -lt $lines.Count - 1; $i++) {
        $cur  = $lines[$i]
        $next = $lines[$i + 1]
        $isEmpty = ($cur -match '^\s*$')
        $isFullLineComment = (
            ($cur -match '^\s*\#')   -or
            ($cur -match '^\s*\*\*') -or
            ($cur -match '^\s*//')   -or
            ($cur -match '^\s*;')    -or
            ($cur -match '^\s*/\*')  -or
            ($cur -match '^\s*\*/')  -or
            ($cur -match '^\s*\*')
        )
        $hasBlockInlineComment = ($cur -match '/\*.*\*/')
        $hasHashInlineComment = ($cur -match '\s#(?![0-9A-Fa-f]{3,8}\b)')
        $isComment = ($isFullLineComment -or $hasBlockInlineComment -or $hasHashInlineComment)
        if (($isEmpty -or $isComment) -and ($next -notmatch '^\s*(def|class)\b')) {
            $kind = if ($isEmpty) { 'EMPTY' } else { 'COMMENT' }
            "{0}:{1} [{2}] {3}" -f $file, ($i + 1), $kind, ($cur -replace "`t","    ")
        }
    }
}