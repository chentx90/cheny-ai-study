$env:XYQ_ACCESS_KEY = '<YOUR_XYQ_ACCESS_KEY>'
$p = Get-Content '<REPO_ROOT>\06_项目作品集\04_AI漫剧管理器重启\prompt_01.txt' -Raw -Encoding UTF8
pippit-tool-cli generate-video --prompt $p --image '<REPO_ROOT>\06_项目作品集\04_AI漫剧管理器重启\data\works\w42302f6a\assets\ec6035a20\小学二年级妹妹.jpg' --image '<REPO_ROOT>\06_项目作品集\04_AI漫剧管理器重启\data\works\w42302f6a\assets\e46f7a008\少年哥哥.jpg' --ratio 16:9 --resolution 720p --model Seedance_2.0_mini_lite
