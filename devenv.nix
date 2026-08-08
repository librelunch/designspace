{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  packages = with pkgs; [
    gcc
    gccStdenv.cc.cc.lib
    zlib
    just
  ];

  # The commit gates, split by what they cost. `just check` is the fast subset
  # and runs on every commit; the full set takes about a minute and a half, so
  # it runs before a push instead. The justfile is their one definition, which
  # is also what CI calls.
  git-hooks.hooks = {
    check = {
      enable = true;
      name = "commit gates (fast)";
      entry = "just check";
      pass_filenames = false;
      language = "system";
      stages = ["pre-commit"];
    };
    gates = {
      enable = true;
      name = "commit gates (full)";
      entry = "just gates";
      pass_filenames = false;
      language = "system";
      stages = ["pre-push"];
    };
  };

  enterTest = ''
    just gates
  '';
  languages = {
    python = {
      enable = true;
      package = pkgs.python314;
      uv = {
        enable = true;
        sync.enable = true;
      };
    };
  };

  env.LD_LIBRARY_PATH = with pkgs; lib.makeLibraryPath [
    stdenv.cc.cc.lib
    zlib
  ];
}
