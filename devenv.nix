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
    libz
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

  env.LD_LIBRARY_PATH = lib.makeLibraryPath [
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
    "/run/opengl-driver" # libcuda.so, libnvidia-*.so from host driver, only necessary for PyTorch/CUDA
  ];
}
