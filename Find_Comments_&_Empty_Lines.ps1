$excludedDirNames = @(
    'binaries',
    'config',
    'logs',
    'mp3',
    '!!!_Ouput_Video_Files_!!!'
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
Write-Output 'Instructions for an AI Agent: "Below are result of comments and empty lines which should be removed from the code which is inside the files. when removing these below comments, or empty lines, please becareful not to touch or hurt the code. only remove the comment and empty line surgecly, without impacting the code:"'
Get-ChildItem -Recurse -File | Where-Object {
    if ($excludedFileNames -contains $_.Name) { return $false }
    if ($allowedExtensions -notcontains $_.Extension.ToLowerInvariant()) { return $false }
    $dirParts = $_.DirectoryName -split '[\\/]'
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
        if (($isEmpty -or $isComment) -and ($next -notmatch '^\s*(def|class|from|import)\b')) {
            $kind = if ($isEmpty) { 'EMPTY' } else { 'COMMENT' }
            "{0}:{1} [{2}] {3}" -f $file, ($i + 1), $kind, ($cur -replace "`t","    ")
        }
    }
}