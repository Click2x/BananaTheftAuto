# 🍌 How to update Banana Theft Auto

## Already have it (cloned with git)? One-time step to get the Update button

1. Open your Banana Theft Auto folder (the one with `Leonida.bat`).
2. Click the address bar, type `cmd` and press Enter. A command window opens in that folder.
3. Run:

   ```
   git pull
   git submodule update --init --recursive
   ```

4. Close the window and double-click `Leonida.bat`.

From now on you don't need the command window. Just open the menu and press **U (Update)**.

## Using Update

1. Double-click `Leonida.bat`.
2. Press **U**, then **Y** to check GitHub.
3. It shows your version, the latest version and the list of what's new.
4. Press **Y** to update. If you've changed files, it sets your changes aside and puts them back afterwards.
5. If the update needs a rebuild, press **Y** and it rebuilds only what changed.
6. Close the menu and open `Leonida.bat` again so you're running the newest menu.

## New here?

```
git clone --recursive https://github.com/Click2x/BananaTheftAuto
```

Then double-click `Leonida.bat`. Python 3.12 or newer is needed; the menu offers everything else.

## Downloaded as a ZIP?

A ZIP copy can't update itself. Clone it once with the command above, and Update works from then on.

## Problems?

- **"git is not recognized"**: install Git from https://git-scm.com, or run `winget install --id Git.Git -e`.
- **`git pull` says your local changes would be overwritten**: run `git stash`, then `git pull`, then `git stash pop`.
- Still stuck? Ask in the Discord: https://discord.gg/ppNRZDSda
