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
  ];
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
