{
  description = "A basic flake for my Python Projects";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }: (
    flake-utils.lib.eachDefaultSystem
    (system: let
      pkgs = import nixpkgs {
        inherit system;

        config = {
          allowUnfree = true;
          # cudaSupport = true;
        };
      };
    in {
      packages = {
        default = {}; # TODO: Add package here
      };

      apps = {
        # TODO: Add app here
        # default = flake-utils.lib.mkApp {
        #   drv = ...;
        # };
      };

      devShells.default = pkgs.mkShell {
        nativeBuildInputs = [];

        buildInputs = with pkgs; [
          python312
          openai-whisper
          piper-tts
        ];

        packages = [
          (pkgs.python3.withPackages (python-pkgs:
            with python-pkgs; [
              fastapi
              numpy
              ollama
              python-multipart
              pydub
              uvicorn
            ]))
        ];
      };
    })
  );
}
